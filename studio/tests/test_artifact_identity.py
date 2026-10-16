"""Real file mutations must invalidate a resume even when paths/masks do not change."""
from pathlib import Path
import tempfile
import unittest

from studio.artifacts import dataset_identity, require_resume_identity
from test_state_api import fixture_scene


class DatasetIdentityTests(unittest.TestCase):
    def test_same_paths_changed_photograph_or_camera_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            scene = fixture_scene(Path(d))
            names = [p.name for p in (scene / "images").iterdir()]
            before = dataset_identity(scene, names)
            require_resume_identity(before, dataset_identity(scene, names))
            for path in (scene / "images" / names[0], scene / "sparse/0/cameras.bin"):
                data = path.read_bytes()
                path.write_bytes(data + b"changed")
                with self.assertRaisesRegex(ValueError, "写真|사진"):
                    require_resume_identity(before, dataset_identity(scene, names))
                path.write_bytes(data)
            self.assertEqual(before, dataset_identity(scene, names))

    def test_legacy_unverifiable_identity_and_outside_paths_are_rejected(self):
        with self.assertRaises(ValueError):
            require_resume_identity({"scene": "scene"}, {"scene": "scene", "dataset": {}})
        with tempfile.TemporaryDirectory() as d:
            scene = fixture_scene(Path(d))
            with self.assertRaises(ValueError):
                dataset_identity(scene, ["../../outside.png"])
