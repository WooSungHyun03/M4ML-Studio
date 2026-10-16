"""Live Gaussian viewport: protocol conventions, model location and API contract.

These run without a GPU. The real-render proof (pixel-identical frames vs. the original
view.py, browser/desktop interaction, VRAM release) is in docs/GAUSSIAN_VIEWER_INTEGRATION.md
and scripts/ui_live_render_e2e.mjs / desktop_live_render_qa.mjs."""

import json
import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from studio import api
from studio.gaussian_protocol import RemoteRendererClient, camera_message, gl_view_from_colmap, perspective
from studio.providers.render_gaussian_remote import GaussianRemoteRenderingProvider, ply_header
from studio.store import Store
from test_state_api import fixture_scene


def write_ply(path: Path, props, vertices=5, faces=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["ply", "format binary_little_endian 1.0", f"element vertex {vertices}"]
    lines += [f"property float {p}" for p in props]
    if faces:
        lines += [f"element face {faces}", "property list uchar int vertex_indices"]
    lines.append("end_header")
    path.write_bytes(("\n".join(lines) + "\n").encode() + b"\0" * 32)


GAUSSIAN = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "objectmark_score", "scale_0", "scale_1", "rot_0", "rot_1", "rot_2", "rot_3"]


class ProtocolTests(unittest.TestCase):
    def test_view_matrix_round_trips_through_network_gui_conversion(self):
        """What network_gui.receive() does to our message must give back the 3DGS W2C^T."""
        rng = np.random.default_rng(1)
        q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
        w2c = np.eye(4)
        w2c[:3, :3] = q * np.sign(np.linalg.det(q))
        w2c[:3, 3] = rng.normal(size=3)
        msg = camera_message(gl_view_from_colmap(w2c), 640, 480, 0.8, 0.01, 100)
        view = np.reshape(np.array(msg["view_matrix"]), (4, 4))  # torch.reshape in network_gui
        view[:, 1] = -view[:, 1]
        view[:, 2] = -view[:, 2]
        np.testing.assert_allclose(view, w2c.T, atol=1e-12)
        self.assertAlmostEqual(msg["fov_x"], 2 * np.arctan(np.tan(0.4) * 640 / 480))

    def test_perspective_is_standard_opengl(self):
        p = perspective(np.pi / 2, 1.0, 1.0, 10.0)
        near = p @ np.array([0, 0, -1.0, 1])
        far = p @ np.array([0, 0, -10.0, 1])
        self.assertAlmostEqual(near[2] / near[3], -1.0)
        self.assertAlmostEqual(far[2] / far[3], 1.0)

    def test_client_speaks_the_wire_format(self):
        """Loopback server written from network_gui.py's byte layout (protocol test, not GPU proof)."""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        seen = {}

        def serve():
            conn, _ = srv.accept()
            items = json.dumps(["RGB", "ObjectMark"]).encode()
            conn.sendall(struct.pack("<I", len(items)) + items)
            (n,) = struct.unpack("<I", conn.recv(4))
            buf = b""
            while len(buf) < n:
                buf += conn.recv(n - len(buf))
            seen.update(json.loads(buf))
            conn.sendall(bytes(range(4 * 2 * 3)))
            conn.sendall(struct.pack("<I", 5) + b"scene")
            metrics = json.dumps({"#": 7}).encode()
            conn.sendall(struct.pack("<I", len(metrics)) + metrics)
            conn.close()

        threading.Thread(target=serve, daemon=True).start()
        client = RemoteRendererClient("127.0.0.1", port)
        self.assertEqual(client.render_items, ["RGB", "ObjectMark"])
        rgb, scene, metrics = client.request(camera_message(np.eye(4), 4, 2, 0.8, 0.01, 10, render_mode=1))
        client.close()
        srv.close()
        self.assertEqual(len(rgb), 24)
        self.assertEqual((scene, metrics), ("scene", {"#": 7}))
        self.assertEqual(seen["render_mode"], 1)
        self.assertEqual(len(seen["view_matrix"]), 16)


class ModelLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        fixture_scene(self.root)
        self.model = self.root / "runs/t/training"
        for it in (7000, 30000):
            write_ply(self.model / f"point_cloud/iteration_{it}/point_cloud.ply", GAUSSIAN, vertices=11)
        cams = [{"id": i, "img_name": f"{i + 1:06d}", "position": [i * 0.1, 0, 0], "rotation": np.eye(3).tolist(),
                 "width": 16, "height": 16, "fx": 14, "fy": 14} for i in range(3)]
        (self.model / "cameras.json").write_text(json.dumps(cams))
        self.project = {"scene": "scene", "training": {"path": "runs/t/training", "iterations": 30000}}
        self.provider = GaussianRemoteRenderingProvider()

    def tearDown(self):
        self.temp.cleanup()

    def test_latest_valid_iteration_and_explicit_choice(self):
        m = self.provider.locate_model(self.root, self.project)
        self.assertEqual((m["iterations"], m["iteration"], m["gaussians"]), ([7000, 30000], 30000, 11))
        self.assertEqual(self.provider.locate_model(self.root, self.project, 7000)["iteration"], 7000)
        self.assertEqual(len(m["cameras"]), 3)
        self.assertEqual(len(m["target"]), 3)

    def test_mesh_ply_is_not_accepted_as_gaussians(self):
        write_ply(self.model / "point_cloud/iteration_30000/point_cloud.ply", ["x", "y", "z", "red", "green", "blue"], faces=4)
        with self.assertRaises(ValueError):
            self.provider.locate_model(self.root, self.project)
        self.assertIn("face", ply_header(self.model / "point_cloud/iteration_30000/point_cloud.ply")["elements"])

    def test_cameras_from_another_dataset_are_rejected(self):
        cams = json.loads((self.model / "cameras.json").read_text())
        cams[0]["img_name"] = "IMG_9999"
        (self.model / "cameras.json").write_text(json.dumps(cams))
        with self.assertRaises(ValueError):
            self.provider.locate_model(self.root, self.project)

    def test_no_training_and_path_escape(self):
        with self.assertRaises(FileNotFoundError):
            self.provider.locate_model(self.root, {"scene": "scene"})
        with self.assertRaises(ValueError):
            self.provider.locate_model(self.root, {"scene": "scene", "training": {"path": "../../etc"}})

    def test_modes_only_lists_items_the_server_produces(self):
        modes = self.provider.modes(["RGB", "Alpha", "Normal", "Depth", "Edge", "Curvature", "ObjectMark"])
        self.assertEqual([m["key"] for m in modes], ["rgb", "alpha", "depth", "normal", "objectmark"])
        self.assertEqual(next(m for m in modes if m["key"] == "objectmark")["index"], 6)
        self.assertEqual([m["key"] for m in self.provider.modes(["RGB", "Alpha"])], ["rgb", "alpha"])


class LiveRenderApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.previous = api.store
        api.store = self.store
        self.client = TestClient(api.app)
        self.headers = {"x-studio-token": api.TOKEN}
        self.id = self.store.create("live")["id"]

    def tearDown(self):
        self.client.close()
        api.store = self.previous
        self.temp.cleanup()

    def test_unavailable_without_training_and_frame_needs_session(self):
        info = self.client.get(f"/api/projects/{self.id}/live-render").json()
        self.assertFalse(info["available"])
        body = {"view": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], "fovy": 0.8, "width": 64, "height": 48}
        r = self.client.post(f"/api/projects/{self.id}/live-render/frame", json=body, headers=self.headers)
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.headers.get("x-live-state"), "disconnected")
        self.assertEqual(self.client.post(f"/api/projects/{self.id}/live-render/frame", json=body).status_code, 403)

    def test_frame_request_validation(self):
        bad = {"view": [1, 0, 0], "fovy": 0.8, "width": 64, "height": 48}
        self.assertEqual(self.client.post(f"/api/projects/{self.id}/live-render/frame", json=bad, headers=self.headers).status_code, 422)
        huge = {"view": [0] * 16, "fovy": 0.8, "width": 100000, "height": 48}
        self.assertEqual(self.client.post(f"/api/projects/{self.id}/live-render/frame", json=huge, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.post(f"/api/projects/{self.id}/live-render/stop", headers=self.headers).json(), {"stopped": 0})

    def test_nonfinite_view_and_inverted_clip_planes_rejected_before_renderer(self):
        good = {"view": np.eye(4).T.reshape(-1).tolist(), "fovy": 0.8, "width": 64, "height": 48}
        invalid_view = list(good["view"])
        invalid_view[3] = "NaN"
        for body in ({**good, "view": invalid_view}, {**good, "zfar": "Infinity"},
                     {**good, "znear": 10, "zfar": 1}, {**good, "znear": 1, "zfar": 1}):
            with self.subTest(body=body):
                response = self.client.post(f"/api/projects/{self.id}/live-render/frame", json=body, headers=self.headers)
                self.assertEqual(response.status_code, 422, response.text)
        # Non-standard JSON numeric tokens can be accepted by Python's decoder.
        # Their validation errors must also serialize as 422 instead of crashing.
        for value in (float("nan"), float("inf"), float("-inf")):
            raw = json.dumps({**good, "view": [value] + good["view"][1:]})
            response = self.client.post(f"/api/projects/{self.id}/live-render/frame", content=raw,
                                        headers={**self.headers, "content-type": "application/json"})
            self.assertEqual(response.status_code, 422, response.text)


if __name__ == "__main__":
    unittest.main()
