import json
from pathlib import Path
import sys
import tempfile
import unittest

from studio.doctor import atomic_json, command, sha256


class DoctorTests(unittest.TestCase):
    def test_arguments_are_literal(self):
        literal = "한글 이름 ; $(touch SHOULD_NOT_EXIST)"
        result = command(
            [sys.executable, "-c", "import sys; print(sys.argv[1])", literal]
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["output"].strip(), literal)

    def test_failures_remain_failures(self):
        self.assertEqual(
            command([sys.executable, "-c", "raise SystemExit(7)"])["exit_code"], 7
        )
        self.assertIsNone(command(["/nonexistent/studio-command"])["exit_code"])
        self.assertIsNone(
            command(
                [sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.05
            )["exit_code"]
        )

    def test_atomic_unicode_report_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "한글 보고서.json"
            atomic_json(path, {"상태": "미실행"})
            self.assertEqual(json.loads(path.read_text()), {"상태": "미실행"})
            first = sha256(path)
            atomic_json(path, {"상태": "실패"})
            self.assertNotEqual(first, sha256(path))
            self.assertEqual(list(Path(directory).glob(".report-*")), [])
