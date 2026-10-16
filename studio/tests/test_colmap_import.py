import tempfile, unittest, shutil
from pathlib import Path
from PIL import Image
from studio.colmap_import import inspect_colmap_import, commit_import, safe
from test_state_api import fixture_scene


class ColmapImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.upload = self.root / "import-upload"
        self.upload.mkdir()
        self.scene = fixture_scene(self.upload)

    def tearDown(self):
        self.temp.cleanup()

    def test_real_colmap_binary_import_not_sfm_and_mask_gate(self):
        masks = self.scene / "mask"
        masks.mkdir()
        for p in (self.scene / "images").glob("*.png"):
            Image.new("L", (16, 16), 255).save(masks / p.name)
        options = {"with_masks": True}
        audit = inspect_colmap_import(self.upload, options, self.root / "audit")
        self.assertFalse(audit["blocking_errors"])
        self.assertFalse(audit["mask_errors"])
        result = commit_import(self.root, options)
        self.assertTrue(result["committed"])
        self.assertEqual(len(result["masks"]), 3)
        self.assertFalse(result["provenance"]["undistorted_during_import"])
        self.assertNotIn(
            "feature_extractor", (self.root / "audit/inspect.log").read_text()
        )

    def test_missing_mask_and_wrong_shape_block_c_b_still_valid(self):
        masks = self.scene / "mask"
        masks.mkdir()
        Image.new("L", (15, 16), 255).save(masks / "000001.png")
        audit = inspect_colmap_import(
            self.upload, {"with_masks": True}, self.root / "audit"
        )
        self.assertEqual(len(audit["mask_errors"]), 3)
        result = commit_import(self.root, {"with_masks": True})
        self.assertFalse(result["committed"])
        self.assertTrue(commit_import(self.root, {"with_masks": False})["committed"])

    def test_unsafe_path_missing_photo_and_bad_camera(self):
        with self.assertRaises(ValueError):
            safe(self.root, "../secret")
        (self.scene / "images/000002.png").unlink()
        audit = inspect_colmap_import(self.upload, {}, self.root / "audit")
        self.assertTrue(any("000002.png" in e for e in audit["blocking_errors"]))

    def test_explicit_inversion_and_normalization(self):
        masks = self.scene / "mask"
        masks.mkdir()
        for p in (self.scene / "images").glob("*.png"):
            Image.new("RGB", (16, 16), (0, 0, 0)).save(masks / p.name)
        a = inspect_colmap_import(self.upload, {"with_masks": True}, self.root / "a")
        self.assertEqual(len(a["mask_errors"]), 3)
        b = commit_import(
            self.root,
            {"with_masks": True, "normalize_masks": True, "foreground": "black"},
        )
        self.assertTrue(b["committed"])
