import hashlib, json, tempfile, unittest
from pathlib import Path
import numpy as np
from plyfile import PlyData, PlyElement
from fastapi.testclient import TestClient
from studio import api
from studio.store import Store
from studio.result_artifacts import inspect_result
from studio.project_scan import scan_folder


def gaussian(path, scales=2):
    names = [
        "x",
        "y",
        "z",
        "nx",
        "ny",
        "nz",
        *[f"f_dc_{i}" for i in range(3)],
        "opacity",
        "objectmark_score",
        *[f"scale_{i}" for i in range(scales)],
        *[f"rot_{i}" for i in range(4)],
    ]
    v = np.zeros(4, dtype=[(n, "f4") for n in names])
    v["x"] = [0, 1, 0, 1]
    v["y"] = [0, 0, 1, 1]
    v["rot_0"] = 1
    PlyData([PlyElement.describe(v, "vertex")], text=False).write(path)


def mesh(path):
    import trimesh

    m = trimesh.creation.box()
    m.visual.vertex_colors = [240, 80, 40, 255]
    m.export(path)


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()
        self.store = Store(Path(self.temp.name) / "store")
        self.previous = api.store
        api.store = self.store
        self.client = TestClient(api.app)
        self.headers = {"x-studio-token": api.TOKEN}

    def tearDown(self):
        self.client.close()
        api.store = self.previous
        self.temp.cleanup()

    def test_material_glb_preserves_vertex_colors_and_texture_is_explained(self):
        import trimesh
        from PIL import Image
        from studio.mesh import validate_mesh

        source = self.root / "source.ply"
        mesh(source)
        preview = Path(self.temp.name) / "preview"
        validate_mesh(source, preview)
        glb = self.root / "material.glb"
        glb.write_bytes((preview / "preview.glb").read_bytes())
        before = hashlib.sha256(glb.read_bytes()).hexdigest()
        project = self.store.create("색상 보존")
        api._import_mesh(project["id"], glb, None)
        result = self.store.get(project["id"])["mesh"]
        self.assertTrue(result["colors"], result)
        self.assertGreater(result["color"]["mean_chroma"], 0.5)
        self.assertEqual(hashlib.sha256(glb.read_bytes()).hexdigest(), before)
        uploaded = self.store.create("파일로 색상 가져오기")
        response = self.client.post(
            f'/api/projects/{uploaded["id"]}/mesh-file', headers=self.headers,
            files={"file": ("실제 색상.glb", glb.read_bytes(), "model/gltf-binary")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["mesh"]["colors"])
        self.assertEqual(response.json()["mesh"]["source_name"], "실제 색상.glb")
        # Texture baking is not implemented: reject explicitly instead of losing colour.
        textured = trimesh.creation.box()
        textured.visual = trimesh.visual.texture.TextureVisuals(
            uv=np.zeros((len(textured.vertices), 2)),
            image=Image.new("RGB", (2, 2), "red"),
        )
        texture = self.root / "texture.glb"
        textured.export(texture)
        finding = inspect_result(texture, self.root)
        self.assertFalse(finding["valid"])
        self.assertIn("텍스처", finding["error"])
        tinted = trimesh.creation.box()
        tinted.visual = trimesh.visual.texture.TextureVisuals(
            material=trimesh.visual.material.PBRMaterial(baseColorFactor=[128, 0, 0, 255])
        )
        tint = self.root / "tinted.glb"
        tinted.export(tint)
        finding = inspect_result(tint, self.root)
        self.assertFalse(finding["valid"])
        self.assertIn("재질", finding["error"])

    def test_payload_classification_corruption_unsupported_and_bounds(self):
        gaussian(self.root / "native.ply")
        gaussian(self.root / "other.ply", 3)
        mesh(self.root / "mesh.ply")
        mesh(self.root / "mesh.glb")
        for name, kind, valid in [
            ("native.ply", "gaussian", True),
            ("other.ply", "unsupported", False),
            ("mesh.ply", "mesh", True),
            ("mesh.glb", "mesh", True),
        ]:
            r = inspect_result(self.root / name, self.root)
            self.assertEqual((r["kind"], r["valid"]), (kind, valid), r)
        bad = self.root / "bad.ply"
        bad.write_bytes((self.root / "native.ply").read_bytes()[:-20])
        self.assertFalse(inspect_result(bad, self.root)["valid"])
        huge = self.root / "huge.ply"
        huge.write_text(
            "ply\nformat binary_little_endian 1.0\nelement vertex 999999999999\nproperty float x\nend_header\n"
        )
        self.assertFalse(inspect_result(huge, self.root)["valid"])
        cloud = self.root / "cloud.ply"
        v = np.zeros(2, dtype=[("x", "f4"), ("y", "f4"), ("z", "f4")])
        PlyData([PlyElement.describe(v, "vertex")]).write(cloud)
        self.assertEqual(inspect_result(cloud, self.root)["kind"], "point_cloud")
        nan = self.root / "nan.ply"
        gaussian(nan)
        d = PlyData.read(nan, mmap=False)
        d["vertex"].data["x"][0] = np.nan
        d.write(nan)
        self.assertFalse(inspect_result(nan, self.root)["valid"])

    def test_standalone_both_results_import_selection_and_no_fake_training(self):
        gaussian(self.root / "native.ply")
        mesh(self.root / "mesh.ply")
        mesh(self.root / "second.glb")
        before = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.root.iterdir()
        }
        r = scan_folder(self.root)
        self.assertEqual(r["recommendation"]["stage"], "view")
        self.assertEqual(sum(a["valid"] for a in r["artifacts"]), 3)
        response = self.client.post(
            "/api/projects/from-folder",
            headers=self.headers,
            json={
                "path": str(self.root),
                "artifacts": ["native.ply", "mesh.ply", "second.glb"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        p = response.json()["project"]
        pid = p["id"]
        self.assertNotEqual(p["stages"]["train"], "completed")
        self.assertNotEqual(p["stages"]["colmap"], "completed")
        self.assertIsNone(p.get("training"))
        self.assertEqual(len(p["result_artifacts"]), 3)
        live = self.client.get(
            f"/api/projects/{pid}/live-render", headers=self.headers
        ).json()
        self.assertTrue(live["available"], live)
        self.assertTrue(live["artifact"])
        for a in p["result_artifacts"]:
            self.assertEqual(
                self.client.post(
                    f'/api/projects/{pid}/result-artifacts/{a["id"]}/activate',
                    headers=self.headers,
                ).status_code,
                200,
            )
        self.assertEqual(
            before,
            {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.iterdir()
            },
        )
        bad = self.client.post(
            "/api/projects/from-folder",
            headers=self.headers,
            json={"path": str(self.root), "artifacts": ["../native.ply"]},
        )
        self.assertEqual(bad.status_code, 422)

    def test_real_negative_log_scale_range_and_corrupt_values(self):
        path = self.root / "small-native.ply"
        gaussian(path)
        data = PlyData.read(path, mmap=False)
        data["vertex"].data["scale_0"] = [-67.400734, -65.85201, -80.0, 0.766881]
        data["vertex"].data["scale_1"] = [-65.85201, -67.4, -79.9, -0.033985]
        data.write(path)
        result = inspect_result(path, self.root)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["kind"], "gaussian")
        for prop, value in [
            ("scale_0", float("nan")),
            ("scale_1", float("inf")),
            ("opacity", float("-inf")),
            ("scale_0", 31.0),
            ("scale_1", -81.0),
        ]:
            with self.subTest(prop=prop, value=value):
                gaussian(path)
                data = PlyData.read(path, mmap=False)
                data["vertex"].data[prop][0] = value
                data.write(path)
                self.assertFalse(inspect_result(path, self.root)["valid"])
        gaussian(path)
        data = PlyData.read(path, mmap=False)
        for k in range(4):
            data["vertex"].data[f"rot_{k}"][0] = 0
        data.write(path)
        self.assertFalse(inspect_result(path, self.root)["valid"])

    def test_extreme_native_values_fail_before_cuda(self):
        path = self.root / "extreme.ply"
        gaussian(path)
        data = PlyData.read(path, mmap=False)
        data["vertex"].data["x"][0] = 1e30
        data.write(path)
        self.assertFalse(inspect_result(path, self.root)["valid"])
        gaussian(path)
        data = PlyData.read(path, mmap=False)
        data["vertex"].data["scale_0"][0] = 70
        data.write(path)
        self.assertFalse(inspect_result(path, self.root)["valid"])

    def test_gaussian_only_and_mesh_only_open(self):
        for filename, build in [("only.ply", gaussian), ("only.glb", mesh)]:
            source = self.root / filename
            build(source)
            r = self.client.post(
                "/api/projects/from-folder",
                headers=self.headers,
                json={"path": str(self.root)},
            )
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(len(r.json()["project"]["result_artifacts"]), 1)
            source.unlink()
