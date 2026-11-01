"""T07: untrusted photo uploads and project file downloads.

Unit tests for the validator (metadata stripping is lossless, hostile files are refused,
the worker timeout holds) and gateway tests with a real session backend.
"""

import io
import json
import struct
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from studio_web.security import limits
from studio_web.security import upload_validation as uv
from studio_web.tests.test_gateway import Browser, make_config
from studio_web.app import create_app

GPS = {0x0000: b"\x02\x02\x00\x00", 0x0002: (37.0, 33.0, 0.0), 0x0004: (126.0, 58.0, 0.0)}


def slow_inspect(data):  # module level so the worker process can unpickle it
    time.sleep(5)


def photo(fmt="JPEG", size=(320, 240), exif=None, **kw):
    rng = np.random.default_rng(1)
    image = Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8))
    out = io.BytesIO()
    image.save(out, format=fmt, exif=exif or Image.Exif(), **kw)
    return out.getvalue()


def exif_with_gps(orientation=None):
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    exif[0x0132] = "2026:10:31 12:00:00"
    if orientation:
        exif[0x0112] = orientation
    exif.get_ifd(0x8825).update(GPS)
    return exif


def pixels(data):
    with Image.open(io.BytesIO(data)) as im:
        return im.tobytes()


def png_chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


class Validator(unittest.TestCase):
    def test_jpeg_metadata_is_removed_without_touching_pixels(self):
        data = photo(exif=exif_with_gps())
        self.assertIn(b"PhoneMaker", data)
        clean, info = uv.inspect_and_clean(data)
        self.assertNotIn(b"PhoneMaker", clean)
        with Image.open(io.BytesIO(clean)) as im:
            self.assertEqual(dict(im.getexif()), {})
            self.assertEqual(im.getexif().get_ifd(0x8825), {})
        self.assertEqual(pixels(clean), pixels(data))
        self.assertEqual(info["format"], "JPEG")

    def test_jpeg_orientation_survives_alone(self):
        data = photo(exif=exif_with_gps(orientation=6))
        clean, info = uv.inspect_and_clean(data)
        with Image.open(io.BytesIO(clean)) as im:
            self.assertEqual(dict(im.getexif()), {0x0112: 6})
        self.assertEqual(info["orientation"], 6)
        self.assertEqual(pixels(clean), pixels(data))

    def test_png_text_and_exif_chunks_are_removed(self):
        data = photo("PNG")
        ihdr_end, iend = 8 + 25, data.rindex(b"IEND") - 4  # eXIf belongs before IDAT (PNG spec)
        hostile = (data[:ihdr_end] + png_chunk(b"eXIf", exif_with_gps().tobytes()[6:]) + data[ihdr_end:iend]
                   + png_chunk(b"tEXt", b"Comment\x00secret place") + data[iend:])
        self.assertIn(b"PhoneMaker", hostile)
        clean, _ = uv.inspect_and_clean(hostile)
        self.assertNotIn(b"secret place", clean)
        self.assertNotIn(b"eXIf", clean)
        self.assertNotIn(b"PhoneMaker", clean)
        self.assertEqual(pixels(clean), pixels(hostile))

    def test_plain_files_without_metadata_pass(self):
        # Regression: a PNG without eXIf used to fail (getexif() before verify()).
        for fmt in ("PNG", "JPEG"):
            data = photo(fmt)
            clean, info = uv.inspect_and_clean(data)
            self.assertEqual(info["format"], fmt)
            self.assertEqual(pixels(clean), pixels(data))

    def test_hostile_and_unsupported_files_are_refused(self):
        big_header = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 30000, 30000, 8, 2, 0, 0, 0)) + png_chunk(b"IEND", b"")
        cases = {
            "empty": b"",
            "text renamed": b"hello, not a photo" * 10,
            "gif": photo("GIF"),
            "jpeg magic, junk": b"\xff\xd8\xff" + b"\x00" * 4000,
            "truncated jpeg": photo()[:3000],
            "png bomb header": big_header,
            "tiny": photo(size=(10, 10)),
            "too large": b"\xff\xd8\xff" + b"0" * (uv.MAX_BYTES + 1),
            "tiff": photo("TIFF"),
        }
        for name, data in cases.items():
            with self.assertRaises(uv.UploadRejected, msg=name):
                uv.inspect_and_clean(data)

    def test_worker_timeout_and_recovery(self):
        with mock.patch.object(uv, "WORKER_TIMEOUT", 1), mock.patch.object(uv, "inspect_and_clean", slow_inspect):
            uv._pool = None
            t0 = time.monotonic()
            with self.assertRaises(uv.UploadRejected):
                uv.validate_in_worker(b"x")
            self.assertLess(time.monotonic() - t0, 4)
        clean, info = uv.validate_in_worker(photo())  # a fresh pool works again
        self.assertEqual(info["format"], "JPEG")

    def test_workers_do_not_inherit_open_sockets(self):
        # Regression: forked workers kept the gateway's listening socket (port stayed busy).
        import os, socket
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        listening = os.readlink(f"/proc/self/fd/{listener.fileno()}")  # socket:[inode]
        uv._pool = None
        uv.validate_in_worker(photo())
        workers = list(uv._pool._processes.values())
        for worker in workers:
            fds = os.listdir(f"/proc/{worker.pid}/fd")
            targets = {os.readlink(f"/proc/{worker.pid}/fd/{fd}") for fd in fds if os.path.exists(f"/proc/{worker.pid}/fd/{fd}")}
            self.assertNotIn(listening, targets, f"worker {worker.pid} holds the listening socket")
        listener.close()
        rebind = socket.socket()
        rebind.bind(("127.0.0.1", port))  # the port is free again
        rebind.close()

    def test_display_names(self):
        self.assertEqual(uv.display_name("../../etc/passwd"), "passwd")
        self.assertEqual(uv.display_name("C:\\Users\\me\\IMG_1.JPG"), "IMG_1.JPG")
        self.assertEqual(uv.display_name("a\x00b\nc.jpg"), "abc.jpg")
        self.assertEqual(uv.display_name(""), "사진")
        self.assertEqual(len(uv.display_name("x" * 500 + ".jpg")), 120)


class GatewayUploads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="m4ml-up-")
        cls.home = Path(cls.temp.name) / "web"
        cls.app = create_app(make_config(cls.home))
        cls.addClassCleanup(cls.stop_all)
        cls.a, cls.b = Browser(cls.app), Browser(cls.app)
        cls.a.open()
        cls.b.open()
        cls.pid = cls.a.write("POST", "/api/projects", json={"name": "업로드", "input_mode": "images"}).json()["id"]

    @classmethod
    def stop_all(cls):
        with cls.app.state.db.connect() as db:
            ids = [r["session_id"] for r in db.execute("SELECT session_id FROM backends")]
        for sid in ids:
            cls.app.state.backends.stop(sid)
        cls.temp.cleanup()

    def session_dir(self, browser):
        sid = self.app.state.sessions.lookup(browser.client.cookies.get("__Host-m4ml_session")).id
        return self.app.state.backends.session_dir(sid)

    def upload(self, browser, data, name="IMG_0001.JPG", pid=None, **kw):
        return browser.write("POST", f"/api/projects/{pid or self.pid}/images", files={"file": (name, data, "image/jpeg")}, **kw)

    def test_1_real_photo_is_stored_without_metadata(self):
        data = photo(exif=exif_with_gps(orientation=1), size=(640, 480))
        r = self.upload(self.a, data, name="../../IMG_GPS.JPG")
        self.assertEqual(r.status_code, 200, r.text)
        doc = r.json()
        self.assertEqual(len(doc["images"]), 1)
        self.assertEqual(doc["images"][0]["source_name"], "IMG_GPS.JPG")
        self.assertNotIn(str(self.home), json.dumps(doc))
        stored = list((self.session_dir(self.a) / "data/projects" / self.pid / "input/snapshots").glob("*.original"))
        self.assertEqual(len(stored), 1)
        raw = stored[0].read_bytes()
        self.assertNotIn(b"PhoneMaker", raw)
        self.assertEqual(Image.open(io.BytesIO(raw)).getexif().get_ifd(0x8825), {})

    def test_2_refusals(self):
        self.assertEqual(self.a.client.post(f"/api/projects/{self.pid}/images", files={"file": ("x.jpg", photo())},
                                            headers={"origin": "https://127.0.0.1"}).status_code, 403)
        self.assertEqual(self.upload(self.a, photo("GIF"), name="x.gif").status_code, 422)
        self.assertEqual(self.upload(self.a, b"not a photo" * 100, name="x.jpg").status_code, 422)
        self.assertEqual(self.upload(self.a, photo(), headers={"content-length": str(64 * 2**20)}).status_code, 413)
        self.assertEqual(self.upload(self.a, photo(), pid="not-a-project").status_code, 404)
        self.assertEqual(self.upload(self.b, photo(), pid=self.pid).status_code, 404)  # A's project from B
        self.assertEqual(len(self.a.client.get(f"/api/projects/{self.pid}").json()["images"]), 1)

    def test_3_limits(self):
        count = len(self.a.client.get(f"/api/projects/{self.pid}").json()["images"])
        with mock.patch.object(limits, "MAX_PHOTOS_PER_PROJECT", count):
            r = self.upload(self.a, photo(size=(400, 300)))
            self.assertEqual(r.status_code, 413)
            self.assertIn(f"{count}장까지", r.json()["detail"])
        with mock.patch.object(limits, "MIN_FREE_BYTES", 10**15):
            self.assertEqual(self.upload(self.a, photo(size=(400, 300))).status_code, 413)
        with mock.patch.object(limits, "SESSION_BYTES", 1):
            self.assertIn("저장 용량", self.upload(self.a, photo(size=(400, 300))).json()["detail"])

    def test_4_download_with_range_and_ownership(self):
        model = self.session_dir(self.a) / "data/projects" / self.pid / "runs/abc/mesh/fuse_post.ply"
        model.parent.mkdir(parents=True, exist_ok=True)
        payload = b"ply\nformat binary_little_endian 1.0\nend_header\n" + bytes(range(256)) * 400
        model.write_bytes(payload)
        url = f"/api/projects/{self.pid}/files/runs/abc/mesh/fuse_post.ply"
        full = self.a.client.get(url)
        self.assertEqual(full.status_code, 200)
        self.assertEqual(full.content, payload)
        part = self.a.client.get(url, headers={"range": "bytes=100-199"})
        self.assertEqual(part.status_code, 206)
        self.assertEqual(part.content, payload[100:200])
        self.assertEqual(self.b.client.get(url).status_code, 404)
        (model.parent / "run.log").write_text("/srv/secret/path")
        self.assertEqual(self.a.client.get(url.replace("fuse_post.ply", "run.log")).status_code, 404)


if __name__ == "__main__":
    unittest.main()
