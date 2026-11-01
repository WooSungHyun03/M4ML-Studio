"""Session sandbox: argv construction, and (when this host allows it) a live isolation check."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from studio_web.runtime.sandbox import SandboxSpec, bwrap_argv, environment

ROOT = Path(__file__).resolve().parents[2]


def bwrap_usable():
    try:
        return subprocess.run(["bwrap", "--unshare-user", "--unshare-net", "--ro-bind", "/", "/", "true"],
                              capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class Argv(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.session = Path(self.temp.name) / "s"
        self.session.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_defaults_isolate_network_and_keep_secrets_off_the_command_line(self):
        spec = SandboxSpec(self.session, (ROOT / "studio",), env={"STUDIO_TOKEN": "s3cret-token"})
        argv = bwrap_argv(spec, ["true"], bwrap="/usr/bin/bwrap")
        self.assertIn("--unshare-net", argv)
        self.assertNotIn("--setenv", argv)
        self.assertFalse(any("s3cret-token" in a for a in argv))  # /proc/<pid>/cmdline is world-readable
        self.assertEqual(environment(spec)["STUDIO_TOKEN"], "s3cret-token")
        self.assertEqual(argv[argv.index("--bind") + 1: argv.index("--bind") + 3], [str(self.session.resolve()), "/session"])
        self.assertEqual(argv[-2:], ["--", "true"])

    def test_overlapping_and_missing_paths_are_refused(self):
        with self.assertRaises(ValueError):
            bwrap_argv(SandboxSpec(self.session, (self.session.parent,)), ["true"], bwrap="/usr/bin/bwrap")
        with self.assertRaises(ValueError):
            bwrap_argv(SandboxSpec(self.session, (Path(self.temp.name) / "absent",)), ["true"], bwrap="/usr/bin/bwrap")
        with self.assertRaises(ValueError):
            bwrap_argv(SandboxSpec(Path(self.temp.name) / "absent", ()), ["true"], bwrap="/usr/bin/bwrap")


@unittest.skipUnless(bwrap_usable(), "unprivileged bwrap is not allowed in this context")
class LiveIsolation(unittest.TestCase):
    def test_other_session_and_home_are_invisible(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a", Path(d) / "b"
            for s in (a, b):
                (s / "home").mkdir(parents=True)
                (s / "secret").write_text(s.name)
            code = ("import json, os, socket\nfrom pathlib import Path\n"
                    "r = {'own': Path('/session/secret').read_text(), 'other': os.path.exists(%r),"
                    " 'home': sorted(os.listdir('/home'))}\n"
                    "try:\n    socket.create_connection(('1.1.1.1', 443), timeout=2); r['net'] = True\n"
                    "except OSError:\n    r['net'] = False\nprint(json.dumps(r))\n") % str(b / "secret")
            spec = SandboxSpec(a, (Path(sys.executable).resolve().parents[1],), gpu=False)
            result = json.loads(subprocess.run(bwrap_argv(spec, [sys.executable, "-c", code]), env=environment(spec),
                                               capture_output=True, text=True, timeout=60, check=True).stdout)
        self.assertEqual(result["own"], "a")
        self.assertFalse(result["other"])
        self.assertFalse(result["net"])
        self.assertTrue(set(result["home"]) <= {Path.home().name}, result["home"])


if __name__ == "__main__":
    unittest.main()
