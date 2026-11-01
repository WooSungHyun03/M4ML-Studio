"""The test suite must never open the user's real M4ML Studio data.

studio.api builds its Store at import time, so a test module that imports it without first
pointing STUDIO_DATA at a temporary directory opens (and switches to WAL) the desktop
user's ~/.local/share store. Run the API-importing modules with a fresh HOME and check
that nothing appears in the default data locations."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[1]


class UserDataIsolation(unittest.TestCase):
    def test_api_importing_modules_use_temporary_data(self):
        with tempfile.TemporaryDirectory() as home:
            env = {
                key: value
                for key, value in os.environ.items()
                if key not in {"STUDIO_DATA", "XDG_DATA_HOME", "XDG_CONFIG_HOME"}
            }
            env["HOME"] = home
            modules = sorted(
                path.stem for path in TESTS.glob("test_*.py")
                if path.name != Path(__file__).name and "from studio import api" in path.read_text()
            )
            self.assertGreaterEqual(len(modules), 4)
            code = (
                "import sys; sys.path[:0] = [%r, %r]\n" % (str(TESTS), str(ROOT))
                + "".join(f"import {name}\n" for name in modules)
                + "from studio import api\nprint(api.store.root)\n"
            )
            result = subprocess.run(
                [sys.executable, "-c", code], cwd=ROOT, env=env,
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            share = Path(home) / ".local/share"
            for name in ("object-aware-studio", "m4ml-studio"):
                self.assertFalse((share / name).exists(), f"{name} was created in the user's data home")
            self.assertFalse(Path(result.stdout.strip()).is_relative_to(home))


if __name__ == "__main__":
    unittest.main()
