import base64
from io import BytesIO
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from fastapi.testclient import TestClient

from studio import api
from studio.doctor import atomic_json
from studio.importer import import_image, atomic_bytes
from studio.sam31 import validate_mask
from studio.store import Store, invalidate


def png(color="red", mode="RGB", size=(16, 16)):
    im = Image.new(mode, size, color)
    out = BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def fixture_scene(root):
    scene = root / "scene"
    sparse = scene / "sparse/0"
    sparse.mkdir(parents=True)
    (scene / "images").mkdir()
    (sparse / "cameras.bin").write_bytes(
        struct.pack("<QiiQQdddd", 1, 1, 1, 16, 16, 14, 14, 8, 8)
    )
    data = struct.pack("<Q", 3)
    for i in range(1, 4):
        name = f"{i:06d}.png"
        (scene / "images" / name).write_bytes(png())
        data += (
            struct.pack("<idddddddi", i, 1, 0, 0, 0, i * 0.1, 0, 0, 1)
            + name.encode()
            + b"\0"
            + struct.pack("<Q", 0)
        )
    (sparse / "images.bin").write_bytes(data)
    points = struct.pack("<Q", 4)
    for i, (x, y) in enumerate(((-0.2, 0), (0.2, 0), (0, -0.2), (0, 0.2))):
        points += struct.pack("<QdddBBBdQ", i + 1, x, y, 2.0, 255, 255, 255, 0.0, 0)
    (sparse / "points3D.bin").write_bytes(points)
    return scene


class StateAndAPITests(unittest.TestCase):
    def test_cancel_before_worker_pid_is_recorded_is_durable(self):
        job = self.store.new_job(self.id, "colmap", {})
        self.assertFalse(self.store.job(job)["pid"])
        response = self.client.post(self.url + "/cancel", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.store.job(job)["cancel_requested"])
        # Dispatch creates this directory before Popen; emulate that paused boundary.
        (self.root / "logs").mkdir()
        result = subprocess.run(
            [sys.executable, "-m", "studio.worker", job],
            env={**os.environ, "STUDIO_DATA": str(self.store.root)},
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(self.store.job(job)["state"], "cancelled", result.stderr)

    def test_cancel_does_not_signal_an_unrelated_process_after_pid_reuse(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            job = self.store.new_job(self.id, "train", {})
            self.store.job_update(job, pid=child.pid)
            r = self.client.post(self.url + "/cancel", headers=self.headers)
            self.assertEqual(r.status_code, 200)
            time.sleep(.05)
            self.assertIsNone(child.poll(), "cancel signalled a PID that does not belong to this job")
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.previous = api.store
        api.store = self.store
        self.client = TestClient(api.app)
        self.headers = {"x-studio-token": api.TOKEN}
        self.p = self.store.create("테스트 프로젝트")
        self.id = self.p["id"]
        self.root = self.store.path(self.id)
        self.url = f"/api/projects/{self.id}"

    def tearDown(self):
        self.client.close()
        api.store = self.previous
        self.temp.cleanup()

    def seed_review(self):
        fixture_scene(self.root)
        masks = {}
        for i in range(1, 4):
            name = f"{i:06d}.png"
            path = self.root / "masks" / name
            atomic_bytes(path, png(255, mode="L"))
            masks[name] = {
                **validate_mask(path, (16, 16)),
                "path": f"masks/{name}",
                "status": "generated",
                "valid": True,
            }

        def update(p):
            p["scene"] = "scene"
            p["masks"] = masks
            p["target_confirmed"] = True
            p["stages"].update(
                colmap="completed", sam="completed", review="review_required"
            )

        self.store.update(self.id, update)

    def test_auth_origin_and_path_escape(self):
        self.assertEqual(
            self.client.post("/api/projects", json={"name": "x"}).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                "/api/projects",
                json={"name": "x"},
                headers={**self.headers, "origin": "http://evil.test"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get("/api/projects", headers={"host": "evil.test"}).status_code,
            403,
        )
        outside = Path(self.temp.name) / "secret.json"
        outside.write_text("{}")
        (self.root / "escape.json").symlink_to(outside)
        self.assertEqual(
            self.client.get(self.url + "/files/escape.json").status_code, 403
        )

    def test_archive_and_restore_preserve_project_files(self):
        response = self.client.delete(self.url, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["archived"])
        self.assertTrue((self.root / "manifest.json").is_file())
        self.assertFalse(
            self.client.post(self.url + "/restore", headers=self.headers).json()[
                "archived"
            ]
        )

    def test_large_request_and_unapproved_preview_propagation_blocked(self):
        response = self.client.post(
            self.url + "/images",
            headers={**self.headers, "content-length": str(200 * 1024**2)},
            content=b"",
        )
        self.assertEqual(response.status_code, 413)
        self.seed_review()
        with patch(
            "studio.api.health", return_value={"gpus": [{"index": 0, "free_mb": 10000}]}
        ), patch("studio.api.launch") as launch:
            response = self.client.post(
                self.url + "/jobs/sam",
                headers=self.headers,
                json={
                    "reference": "000001.png",
                    "points": [[4, 4]],
                    "labels": [1],
                    "confirmed": True,
                },
            )
            self.assertEqual(response.status_code, 422)
            launch.assert_not_called()

    def test_import_unicode_duplicates_corruption_and_exif(self):
        exif = Image.Exif()
        exif[274] = 6
        out = BytesIO()
        Image.new("RGB", (20, 10), "red").save(out, format="JPEG", exif=exif)
        original = out.getvalue()
        response = self.client.post(
            self.url + "/images",
            headers=self.headers,
            files={"file": ("한글 이름 ; $(x).jpg", original, "image/jpeg")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["images"][0]
        self.assertEqual(item["size"], [10, 20])
        self.assertEqual(
            (self.root / "input/snapshots/000001.original").read_bytes(), original
        )
        self.client.post(
            self.url + "/images",
            headers=self.headers,
            files={"file": ("duplicate.jpg", original, "image/jpeg")},
        )
        p = self.store.get(self.id)
        self.assertEqual(p["images"][1]["duplicate_of"], "000001.png")
        response = self.client.post(
            self.url + "/images",
            headers=self.headers,
            files={"file": ("bad.png", b"not an image", "image/png")},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(len(self.store.get(self.id)["import_errors"]), 1)
        self.assertEqual(
            self.client.post(
                self.url + "/import-complete", headers=self.headers
            ).status_code,
            422,
        )

    def test_skip_blocks_missing_and_records_skip_without_manual_approval(self):
        self.seed_review()
        (self.root / "masks/000002.png").unlink()
        self.assertEqual(
            self.client.post(
                self.url + "/skip-review",
                json={"confirmed": True},
                headers=self.headers,
            ).status_code,
            404,
        )
        self.assertTrue(
            all(
                m["status"] == "generated"
                for m in self.store.get(self.id)["masks"].values()
            )
        )
        atomic_bytes(self.root / "masks/000002.png", png(255, mode="L"))
        response = self.client.post(
            self.url + "/skip-review", json={"confirmed": True}, headers=self.headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(
            all(m["status"] == "skipped" for m in response.json()["masks"].values())
        )
        self.assertEqual(response.json()["stages"]["review"], "completed")

    def test_manual_binary_save_invalidates_training_and_mesh(self):
        self.seed_review()
        self.store.update(
            self.id, lambda p: p["masks"]["000001.png"].update(error="이전 마스크 오류")
        )
        self.store.update(
            self.id, lambda p: p["stages"].update(train="completed", mesh="completed")
        )
        image = Image.new("RGBA", (16, 16), (0, 0, 0, 255))
        image.putpixel((8, 8), (255, 255, 255, 255))
        data = BytesIO()
        image.save(data, format="PNG")
        response = self.client.put(
            self.url + "/masks/000001.png",
            json={"png": base64.b64encode(data.getvalue()).decode(), "approve": True},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        p = response.json()
        self.assertEqual(p["stages"]["train"], "pending")
        self.assertEqual(p["stages"]["mesh"], "pending")
        self.assertEqual(p["masks"]["000001.png"]["status"], "manual")
        confirmed = self.client.put(
            self.url + "/masks/000001.png", json={"approve": True}, headers=self.headers
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.json()["masks"]["000001.png"]["status"], "manual")
        self.assertEqual(confirmed.json()["masks"]["000001.png"]["sha256"], p["masks"]["000001.png"]["sha256"])
        self.assertNotIn("error", p["masks"]["000001.png"])
        with Image.open(self.root / p["masks"]["000001.png"]["path"]) as saved:
            self.assertEqual(saved.mode, "L")
        invalid = base64.b64encode(png(127, mode="L")).decode()
        self.assertEqual(
            self.client.put(
                self.url + "/masks/000001.png",
                json={"png": invalid},
                headers=self.headers,
            ).status_code,
            422,
        )
        self.assertEqual(self.store.get(self.id)["masks"]["000001.png"]["area"], 1)

    def test_training_requires_approval_and_complete_masks(self):
        self.seed_review()
        with patch(
            "studio.api.health", return_value={"gpus": [{"index": 0, "free_mb": 10000}]}
        ), patch("studio.api.launch") as launch:
            response = self.client.post(
                self.url + "/jobs/train", json={"confirmed": True}, headers=self.headers
            )
            self.assertEqual(response.status_code, 422)
            launch.assert_not_called()
            self.client.post(
                self.url + "/skip-review",
                json={"confirmed": True},
                headers=self.headers,
            )
            self.assertEqual(
                self.client.post(
                    self.url + "/jobs/train",
                    json={"confirmed": False},
                    headers=self.headers,
                ).status_code,
                422,
            )
            launch.assert_not_called()
            launch.return_value = "fixture"
            response = self.client.post(
                self.url + "/jobs/train", json={"confirmed": True}, headers=self.headers
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(launch.call_args.args[3]["iterations"], 30000)

    def test_no_gpu_low_disk_and_duplicate_request_gates(self):
        self.seed_review()
        with patch("studio.api.health", return_value={"gpus": []}), patch(
            "studio.api.launch"
        ) as launch:
            response = self.client.post(
                self.url + "/jobs/preview",
                headers=self.headers,
                json={"reference": "000001.png", "points": [[4, 4]], "labels": [1]},
            )
            self.assertEqual(response.status_code, 422)
            launch.assert_not_called()
        from collections import namedtuple

        usage = namedtuple("Usage", "total used free")(10 * 1024**3, 10 * 1024**3, 1)
        with patch("studio.api.shutil.disk_usage", return_value=usage):
            response = self.client.post(
                self.url + "/images",
                headers=self.headers,
                files={"file": ("file.png", png(), "image/png")},
            )
            self.assertEqual(response.status_code, 422)
        self.store.new_job(self.id, "colmap", {})
        self.assertEqual(
            self.client.post(
                self.url + "/jobs/colmap", headers=self.headers, json={}
            ).status_code,
            409,
        )

    def test_restart_orphan_and_duplicate_job_recovery(self):
        job = self.store.new_job(self.id, "colmap", {})
        import sqlite3

        with self.assertRaises(sqlite3.IntegrityError):
            self.store.new_job(self.id, "colmap", {})
        self.store.job_update(job, pid=99999999)
        self.store.update(self.id, lambda p: p["stages"].update(colmap="running"))
        restored = Store(self.temp.name)
        restored.reconcile()
        self.assertEqual(restored.get(self.id)["stages"]["colmap"], "cancelled")
        self.assertEqual(restored.job(job)["state"], "cancelled")
        self.assertEqual(
            json.loads((self.root / "manifest.json").read_text())["stages"]["colmap"],
            "cancelled",
        )

    def test_restart_revalidates_deleted_mask_and_corrupt_camera_artifacts(self):
        self.seed_review()
        self.client.post(
            self.url + "/skip-review", headers=self.headers, json={"confirmed": True}
        )
        (self.root / "masks/000002.png").unlink()
        self.store.audit_artifacts(self.id)
        p = self.store.get(self.id)
        self.assertEqual(p["stages"]["review"], "review_required")
        self.assertFalse(p["masks"]["000002.png"]["valid"])
        (self.root / "scene/sparse/0/cameras.bin").write_bytes(b"corrupt")
        self.store.audit_artifacts(self.id)
        self.assertEqual(self.store.get(self.id)["stages"]["colmap"], "failed")
        self.assertEqual(self.store.get(self.id)["stages"]["train"], "pending")

    def test_orphan_reconciliation_for_all_scientific_stages(self):
        for stage in ("colmap", "preview", "sam", "train", "mesh"):
            with self.subTest(stage=stage):
                p = self.store.create(stage)
                job = self.store.new_job(p["id"], stage, {})
                self.store.job_update(job, pid=99999999)
                self.store.reconcile()
                self.assertEqual(self.store.job(job)["state"], "cancelled")
                target = "sam" if stage == "preview" else stage
                self.assertEqual(self.store.get(p["id"])["stages"][target], "cancelled")
