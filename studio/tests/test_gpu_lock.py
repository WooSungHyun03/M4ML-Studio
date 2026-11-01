"""GPU lock location: per-user by default, shared across accounts with STUDIO_GPU_LOCK_DIR."""

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from studio import gpu_lock

ROOT = Path(__file__).resolve().parents[2]
HOLD = "import sys; sys.path.insert(0, %r)\nfrom studio import gpu_lock\nh = gpu_lock.try_acquire('dev')\nprint('HELD' if h else 'BUSY', flush=True)\nsys.stdin.read()\n"


class GpuLockLocation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def env(self, runtime, shared=None):
        (self.dir / runtime).mkdir(exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k != "STUDIO_GPU_LOCK_DIR"}
        env["XDG_RUNTIME_DIR"] = str(self.dir / runtime)
        if shared:
            env["STUDIO_GPU_LOCK_DIR"] = str(shared)
        return env

    def held_by_other_process(self, env):
        holder = subprocess.Popen([sys.executable, "-c", HOLD % str(ROOT)], env=env,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.stdin.close)
        self.assertEqual(holder.stdout.readline().strip(), "HELD")

    def test_default_directories_are_per_user(self):
        # Documents the reason for STUDIO_GPU_LOCK_DIR: two accounts never see each other's lock.
        self.held_by_other_process(self.env("user-a"))
        with mock.patch.dict(os.environ, self.env("user-b")):
            handle = gpu_lock.try_acquire("dev")
        self.assertIsNotNone(handle)
        handle.close()

    def test_shared_directory_excludes_across_runtime_dirs(self):
        shared = self.dir / "shared"
        shared.mkdir()
        self.held_by_other_process(self.env("user-a", shared))
        with mock.patch.dict(os.environ, self.env("user-b", shared)):
            self.assertIsNone(gpu_lock.try_acquire("dev"))
            self.assertEqual(gpu_lock.lock_path("dev").parent, shared)

    def test_missing_shared_directory_is_an_error_not_a_silent_private_lock(self):
        with mock.patch.dict(os.environ, self.env("user-a", self.dir / "absent")):
            with self.assertRaises(RuntimeError):
                gpu_lock.try_acquire("dev")
        self.assertFalse((self.dir / "absent").exists())

    def test_read_only_lock_file_from_another_account_still_locks(self):
        shared = self.dir / "shared"
        shared.mkdir()
        with mock.patch.dict(os.environ, self.env("user-a", shared)):
            path = gpu_lock.lock_path("dev")
            path.touch()
            path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            if os.access(path, os.W_OK):
                self.skipTest("running as root: permissions are not enforced")
            first = gpu_lock.try_acquire("dev")
            self.assertIsNotNone(first)
            self.held_by_nobody_else(path)
            first.close()

    def held_by_nobody_else(self, path):
        code = ("import fcntl, sys\nh = open(%r)\ntry:\n    fcntl.flock(h, fcntl.LOCK_EX | fcntl.LOCK_NB); print('FREE')\n"
                "except BlockingIOError:\n    print('BUSY')\n") % str(path)
        self.assertEqual(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout.strip(), "BUSY")


if __name__ == "__main__":
    unittest.main()
