from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest

from studio.colmap import database_report
from studio.process import Cancelled, run


class RealProcessTests(unittest.TestCase):
    def test_failure_and_timeout_preserve_log(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "실행 기록.log"
            with self.assertRaisesRegex(RuntimeError, "종료 코드 9"):
                run(
                    [
                        sys.executable,
                        "-c",
                        "print('real child failure', flush=True); raise SystemExit(9)",
                    ],
                    log,
                )
            self.assertIn("real child failure", log.read_text())
            with self.assertRaises(TimeoutError):
                run(
                    [sys.executable, "-c", "import time; time.sleep(10)"],
                    log,
                    timeout=0.1,
                )

    def test_cancel_real_child_process(self):
        with tempfile.TemporaryDirectory() as d:
            token = threading.Event()
            timer = threading.Timer(0.2, token.set)
            timer.start()
            try:
                with self.assertRaises(Cancelled):
                    run(
                        [sys.executable, "-c", "import time; time.sleep(10)"],
                        Path(d) / "cancel.log",
                        cancel=token,
                    )
            finally:
                timer.cancel()


class RegistrationAuditTests(unittest.TestCase):
    def test_verified_matching_does_not_imply_pose_registration(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "db.sqlite"
            with sqlite3.connect(path) as db:
                db.executescript(
                    "CREATE TABLE images(image_id INTEGER,name TEXT); CREATE TABLE keypoints(image_id INTEGER, rows INTEGER); CREATE TABLE two_view_geometries(pair_id INTEGER, rows INTEGER);"
                )
                db.executemany(
                    "INSERT INTO images VALUES (?,?)",
                    [(i, str(i) + ".png") for i in range(1, 6)],
                )
                db.executemany(
                    "INSERT INTO keypoints VALUES (?,?)",
                    [(i, 100) for i in range(1, 6)],
                )
                db.executemany(
                    "INSERT INTO two_view_geometries VALUES (?,?)",
                    [
                        (2147483647 + 2, 35),
                        (2 * 2147483647 + 3, 25),
                        (3 * 2147483647 + 4, 0),
                    ],
                )
            report = database_report(
                path, {"1.png", "2.png"}, {"0": {"1.png", "2.png"}, "1": {"4.png"}}
            )
            rows = {i["name"]: i for i in report["images"]}
            self.assertTrue(rows["3.png"]["has_verified_match"])
            self.assertFalse(rows["3.png"]["registered"])
            self.assertEqual(rows["3.png"]["reason"], "매칭되었으나 카메라 등록 실패")
            self.assertEqual(rows["4.png"]["reason"], "다른 재구성 그룹")
            self.assertFalse(rows["4.png"]["has_verified_match"])
            self.assertEqual(rows["5.png"]["reason"], "미매칭")
            self.assertEqual(report["registered"], 2)
            self.assertEqual(report["verified_pairs"], 2)
