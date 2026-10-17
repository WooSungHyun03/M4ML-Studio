"""Folder analysis (studio/project_scan.py) on real COLMAP binary / PLY fixtures.

Synthetic data only: these prove the integrity rules, not reconstruction quality."""

import hashlib, json, tempfile, unittest
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient
from studio import api
from studio.project_scan import scan_folder
from studio.store import Store
from test_state_api import fixture_scene, png


def tree_hash(root: Path):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def ply(path: Path, vertices=3, faces=1, colors=True, props=()):
    """Minimal binary PLY with the header elements the scanner reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "ply",
        "format binary_little_endian 1.0",
        f"element vertex {vertices}",
        "property float x",
        "property float y",
        "property float z",
    ]
    lines += [f"property float {p}" for p in props]
    if colors:
        lines += ["property uchar red", "property uchar green", "property uchar blue"]
    if faces:
        lines += [f"element face {faces}", "property list uchar int vertex_indices"]
    lines.append("end_header")
    import struct

    payload = b"".join(
        struct.pack("<fff", float(i % 3), float(i // 3), 0.0)
        + b"\0" * (4 * len(props))
        + (bytes([255, 100, 40]) if colors else b"")
        for i in range(vertices)
    )
    if faces:
        payload += b"".join(struct.pack("<Biii", 3, 0, 1, 2) for _ in range(faces))
    path.write_bytes(("\n".join(lines) + "\n").encode() + payload)


def training_output(
    scene: Path, centres_offset=0.0, iterations=(30000,), checkpoints=()
):
    """2DGS output folder whose cameras.json matches the fixture poses (centre = -Rᵀt)."""
    out = scene / "output"
    out.mkdir(parents=True, exist_ok=True)
    (out / "cfg_args").write_text(
        f"Namespace(source_path='{scene}', model_path='{out}')"
    )
    cams = [
        {
            "id": i - 1,
            "img_name": f"{i:06d}",
            "position": [-i * 0.1 + centres_offset, 0.0, 0.0],
        }
        for i in range(1, 4)
    ]
    (out / "cameras.json").write_text(json.dumps(cams))
    for it in iterations:
        from test_result_artifacts import gaussian

        target = out / f"point_cloud/iteration_{it}/point_cloud.ply"
        target.parent.mkdir(parents=True)
        gaussian(target)
    for c in checkpoints:
        (out / f"chkpnt{c}.pth").write_bytes(b"PK\x03\x04" + b"\0" * 32)
    return out


class ProjectScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "data" / "capture"
        self.root.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def scan(self):
        before = tree_hash(self.root)
        result = scan_folder(self.root)
        self.assertEqual(before, tree_hash(self.root), "scan must not modify the source folder")
        return result

    def test_photos_only_starts_with_camera_registration(self):
        (self.root / "photos").mkdir()
        for i in range(4):
            (self.root / f"photos/IMG_{i}.png").write_bytes(png())
        r = self.scan()
        self.assertEqual(r["recommendation"]["stage"], "colmap")
        self.assertEqual(r["images"]["count"], 4)
        self.assertIsNone(r["selected_sparse"])

    def test_registered_cameras_then_masks(self):
        scene = fixture_scene(self.root)
        r = self.scan()
        self.assertEqual(r["recommendation"]["stage"], "sam")
        self.assertEqual(next(x for x in r["sparse"] if x["path"] == r["selected_sparse"])["registered"], 3)
        (scene / "mask").mkdir()
        for p in (scene / "images").glob("*.png"):
            Image.new("L", (16, 16), 255).save(scene / "mask" / p.name)
        self.assertEqual(self.scan()["recommendation"]["stage"], "train")

    def test_wrong_size_mask_is_a_problem_not_a_pass(self):
        scene = fixture_scene(self.root)
        (scene / "mask").mkdir()
        Image.new("L", (15, 16), 255).save(scene / "mask/000001.png")
        for name in ("000002.png", "000003.png"):
            Image.new("L", (16, 16), 255).save(scene / "mask" / name)
        r = self.scan()
        self.assertNotEqual(r["recommendation"]["stage"], "train")
        self.assertTrue(any("000001" in p for p in r["problems"]))

    def test_matching_training_and_mesh_are_reused(self):
        scene = fixture_scene(self.root)
        out = training_output(scene)
        ply(out / "train/ours_30000/fuse_post.ply")
        r = self.scan()
        self.assertEqual(r["recommendation"]["stage"], "view")
        t = r["training"][0]
        self.assertEqual(t["dataset_match"], "yes")
        self.assertTrue(t["has_objectmark"])
        self.assertTrue(r["meshes"][0]["usable"])

    def test_foreign_training_and_its_mesh_are_never_attached(self):
        scene = fixture_scene(self.root)
        out = training_output(scene, centres_offset=0.5)
        ply(out / "train/ours_30000/fuse_post.ply")
        r = self.scan()
        self.assertEqual(r["training"][0]["dataset_match"], "no")
        self.assertEqual(r["recommendation"]["stage"], "sam")
        self.assertFalse(r["meshes"][0]["usable"])
        self.assertTrue(any("일치하지 않아" in p for p in r["problems"]))
        self.assertFalse(any("함께 열 수" in x for x in r["recommendation"]["reasons"]))

    def test_checkpoint_without_execution_identity_is_not_assumed_resumable(self):
        scene = fixture_scene(self.root)
        training_output(scene, iterations=(), checkpoints=(2500, 5000))
        r = self.scan()
        self.assertEqual(r["recommendation"]["stage"], "sam")
        self.assertFalse(r["training"][0]["resume_compatible"])

    def test_finished_training_without_mesh_recommends_mesh_extraction(self):
        scene = fixture_scene(self.root)
        training_output(scene)
        self.assertEqual(self.scan()["recommendation"]["stage"], "mesh")

    def test_mesh_only_and_point_cloud_rejection(self):
        ply(self.root / "result.ply")
        ply(self.root / "cloud.ply", faces=0)
        r = self.scan()
        self.assertEqual(r["recommendation"]["stage"], "view")
        bad = next(m for m in r["artifacts"] if m["path"] == "cloud.ply")
        self.assertFalse(bad["valid"])

    def test_empty_folder_has_no_start_stage(self):
        r = self.scan()
        self.assertIsNone(r["recommendation"]["stage"])
        self.assertTrue(r["problems"])


class FolderEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.store = Store(base / "store")
        self.previous = api.store
        api.store = self.store
        self.client = TestClient(api.app)
        self.headers = {"x-studio-token": api.TOKEN}
        self.folder = base / "data" / "capture"
        self.folder.mkdir(parents=True)

    def tearDown(self):
        self.client.close()
        api.store = self.previous
        self.temp.cleanup()

    def test_scan_and_open_preserve_source_and_skip_foreign_results(self):
        scene = fixture_scene(self.folder)
        (scene / "mask").mkdir()
        for p in (scene / "images").glob("*.png"):
            Image.new("L", (16, 16), 255).save(scene / "mask" / p.name)
        training_output(scene, centres_offset=0.5)
        before = tree_hash(self.folder)
        scan = self.client.post("/api/scan-folder", json={"path": str(self.folder)}, headers=self.headers)
        self.assertEqual(scan.status_code, 200, scan.text)
        self.assertEqual(scan.json()["recommendation"]["stage"], "train")
        opened = self.client.post("/api/projects/from-folder", json={"path": str(self.folder)}, headers=self.headers)
        self.assertEqual(opened.status_code, 200, opened.text)
        project = opened.json().get("project", opened.json())
        self.assertIsNone(project.get("training"))
        self.assertIsNone(project.get("mesh"))
        self.assertEqual(project["stages"]["colmap"], "completed")
        self.assertEqual(before, tree_hash(self.folder), "opening must not modify the source folder")

    def test_mutation_requires_token_and_system_folders_are_refused(self):
        self.assertEqual(self.client.post("/api/projects/from-folder", json={"path": str(self.folder)}).status_code, 403)
        r = self.client.post("/api/scan-folder", json={"path": str(Path.home())}, headers=self.headers)
        self.assertEqual(r.status_code, 422)
        self.assertIn("홈 폴더", r.text)


    def test_remove_photo_promotes_exact_duplicate_and_keeps_files(self):
        pid = self.client.post("/api/projects", json={"name": "remove", "input_mode": "images"}, headers=self.headers).json()["id"]
        url = f"/api/projects/{pid}"
        data = png("blue")
        for name in ("a.png", "b.png"):
            self.client.post(url + "/images", files={"file": (name, png("red") if name == "b.png" else data, "image/png")}, headers=self.headers)
        self.client.post(url + "/images", files={"file": ("copy-of-a.png", data, "image/png")}, headers=self.headers)
        images = self.client.get(url).json()["images"]
        original = next(i for i in images if i["source_name"] == "a.png")
        copy = next(i for i in images if i["source_name"] == "copy-of-a.png")
        self.assertEqual(copy["duplicate_of"], original["name"])
        files = tree_hash(self.store.path(pid))
        self.assertEqual(self.client.delete(f"{url}/images/{original['name']}").status_code, 403)
        r = self.client.delete(f"{url}/images/{original['name']}", headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        after = {i["source_name"]: i for i in r.json()["images"]}
        self.assertNotIn("a.png", after)
        self.assertIsNone(after["copy-of-a.png"]["duplicate_of"])
        self.assertTrue(set(files) <= set(tree_hash(self.store.path(pid))), "stored photo files are kept")
        self.store.update(pid, lambda doc: doc["stages"].__setitem__("import", "completed"))
        self.assertNotEqual(self.client.delete(f"{url}/images/{copy['name']}", headers=self.headers).status_code, 200)


if __name__ == "__main__":
    unittest.main()
