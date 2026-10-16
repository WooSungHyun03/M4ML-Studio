import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from studio.doctor import atomic_json, command, sha256


class DoctorTests(unittest.TestCase):
    def test_desktop_check_reports_missing_system_libraries_without_loading_a_window(self):
        from studio.desktop_dependencies import desktop_dependencies
        import types

        spec = types.SimpleNamespace(submodule_search_locations=["/fixture/PySide6"])
        missing = types.SimpleNamespace(returncode=0, stdout="libsmime3.so => not found\nlibxcb-cursor.so.0 => not found\n")
        with patch("importlib.util.find_spec", return_value=spec), patch("subprocess.run", return_value=missing):
            result = desktop_dependencies()
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("libnss3", result["output"])
        self.assertIn("libxcb-cursor0", result["output"])
        with patch("importlib.util.find_spec", return_value=None):
            self.assertEqual(desktop_dependencies()["exit_code"], 1)

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
