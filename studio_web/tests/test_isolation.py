"""T10: session backends share one GPU lock, and (where bwrap is allowed) run sandboxed."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from studio_web import config as config_module
from studio_web.persistence.db import Database
from studio_web.runtime.backends import Backends

ROOT = config_module.ROOT
HOLD = "import sys; sys.path.insert(0, %r)\nfrom studio import gpu_lock\nh = gpu_lock.try_acquire('GPU-0')\nprint('HELD' if h else 'BUSY', flush=True)\nsys.stdin.read()\n"


class PlainBackendStop(unittest.TestCase):
    def test_stop_leaves_no_process_behind(self):
        import asyncio
        from studio_web.auth.sessions import Sessions
        from studio_web.runtime.backends import _descendants, _start_time
        with tempfile.TemporaryDirectory(prefix="m4ml-iso-") as d:
            cfg = config_module.load({"STUDIO_WEB_HOME": d})
            db = Database(cfg.database)
            session, _ = Sessions(db, 7).create()
            backends = Backends(cfg, db)
            backend = asyncio.run(backends.ensure(session.id))
            tree = [(backend.pid, backend.pid_start)] + _descendants(backend.pid)
            self.assertNotIn(backend.token.encode(), Path(f"/proc/{backend.pid}/cmdline").read_bytes())
            backends.stop(session.id)
            self.assertEqual([p for p, s in tree if _start_time(p) == s], [])


class SharedGpuLock(unittest.TestCase):
    def test_two_sessions_exclude_each_other_on_the_gpu(self):
        with tempfile.TemporaryDirectory(prefix="m4ml-iso-") as d:
            cfg = config_module.load({"STUDIO_WEB_HOME": d})
            backends = Backends(cfg, Database(cfg.database))
            env_a, env_b = backends._environment("aaaa", "t1"), backends._environment("bbbb", "t2")
            self.assertNotEqual(env_a["XDG_RUNTIME_DIR"], env_b["XDG_RUNTIME_DIR"])
            self.assertEqual(env_a["STUDIO_GPU_LOCK_DIR"], env_b["STUDIO_GPU_LOCK_DIR"])
            holder = subprocess.Popen([sys.executable, "-c", HOLD % str(ROOT)], env={**os.environ, **env_a},
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(holder.stdout.readline().strip(), "HELD")
                other = subprocess.run([sys.executable, "-c", HOLD % str(ROOT)], env={**os.environ, **env_b},
                                       input="", capture_output=True, text=True, timeout=30)
                self.assertEqual(other.stdout.strip(), "BUSY")
            finally:
                holder.stdin.close()
                holder.wait(10)


def bwrap_usable():
    try:
        return subprocess.run(["bwrap", "--unshare-user", "--unshare-net", "--ro-bind", "/", "/", "true"],
                              capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@unittest.skipUnless(bwrap_usable(), "unprivileged bwrap is not allowed in this context (production needs the AppArmor step)")
class SandboxedBackends(unittest.TestCase):
    """Gateway with STUDIO_WEB_SANDBOX=bwrap and real backends: what does a backend really see?"""

    @classmethod
    def setUpClass(cls):
        from studio_web.app import create_app
        from studio_web.tests.test_gateway import Browser
        cls.Browser = Browser
        cls.temp = tempfile.TemporaryDirectory(prefix="m4ml-sbx-")
        cls.home = Path(cls.temp.name) / "web"
        cfg = config_module.load({"STUDIO_WEB_HOME": str(cls.home), "STUDIO_WEB_SANDBOX": "bwrap",
                                  "STUDIO_WEB_SAM_CHECKPOINT": str(ROOT / "models/sam3.1/sam3.1_multiplex.pt")})
        cls.app = create_app(cfg)
        cls.addClassCleanup(cls.stop_all)
        cls.a, cls.b = Browser(cls.app), Browser(cls.app)
        cls.a.open()
        cls.b.open()
        cls.pa = cls.a.write("POST", "/api/projects", json={"name": "A", "input_mode": "images"}).json()["id"]
        cls.pb = cls.b.write("POST", "/api/projects", json={"name": "B", "input_mode": "images"}).json()["id"]

    @classmethod
    def stop_all(cls):
        with cls.app.state.db.connect() as db:
            ids = [r["session_id"] for r in db.execute("SELECT session_id FROM backends")]
        for sid in ids:
            cls.app.state.backends.stop(sid)
        cls.temp.cleanup()

    def backend(self, browser):
        sid = self.app.state.sessions.lookup(browser.client.cookies.get("__Host-m4ml_session")).id
        return self.app.state.backends.registered(sid), self.app.state.backends.session_dir(sid)

    def view(self, pid):
        # uvicorn runs as bwrap's child; look at the python process's own root directory.
        children = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
        target = next((c for c in children if b"uvicorn" in Path(f"/proc/{c}/cmdline").read_bytes()), children[0] if children else str(pid))
        return Path(f"/proc/{target}/root")

    def test_backend_sees_only_its_own_session(self):
        (ba, dir_a), (bb, dir_b) = self.backend(self.a), self.backend(self.b)
        root = self.view(ba.pid)
        self.assertTrue((root / "session/data/projects" / self.pa).is_dir())
        self.assertFalse((root / "session/data/projects" / self.pb).exists())
        self.assertFalse((root / str(dir_b).lstrip("/")).exists(), "other session folder visible")
        self.assertFalse((root / str(self.home / "gateway.sqlite").lstrip("/")).exists(), "gateway database visible")
        home = root / str(Path.home()).lstrip("/")
        self.assertFalse((home / ".ssh").exists())
        self.assertFalse((home / ".local/share/object-aware-studio").exists(), "desktop data visible")
        for private in ("DTU", "datasets", "evidence", "web-harness", ".git"):
            self.assertFalse((root / str(ROOT / private).lstrip("/")).exists(), private)
        self.assertTrue((root / str(ROOT / "studio/api.py").lstrip("/")).is_file())

    def test_gpu_and_engines_work_inside(self):
        health = self.a.client.get("/api/health").json()
        self.assertTrue(health["gpus"], health)  # nvidia-smi inside the sandbox
        self.assertTrue(health["runtime_status"]["available"], health)  # torch.cuda inside the sandbox
        self.assertTrue(health["colmap"]["available"], health)
        self.assertTrue(health["checkpoint_exists"], health)

    def test_stop_leaves_no_process_and_token_never_on_a_command_line(self):
        from studio_web.runtime.backends import _descendants, _start_time
        c = self.Browser(self.app)
        c.open()
        self.assertEqual(c.client.get("/api/projects").status_code, 200)
        backend, _ = self.backend(c)
        tree = [(backend.pid, backend.pid_start)] + _descendants(backend.pid)
        self.assertGreaterEqual(len(tree), 2)  # bwrap and the backend inside it
        for proc in Path("/proc").iterdir():
            if proc.name.isdigit():
                try:
                    self.assertNotIn(backend.token.encode(), (proc / "cmdline").read_bytes(), proc.name)
                except OSError:
                    pass
        self.app.state.backends.stop(self.app.state.sessions.lookup(c.client.cookies.get("__Host-m4ml_session")).id)
        alive = [pid for pid, start in tree if _start_time(pid) == start]
        self.assertEqual(alive, [], "processes left after stopping a sandboxed backend")

    def test_engine_packages_import_inside_the_sandbox(self):
        # Regression: `sam3` came from an editable install under the user's home (hidden here).
        backends = self.app.state.backends
        code = ("import sam3, diff_surfel_rasterization, simple_knn, torch, studio.worker\n"
                "print(sam3.__file__); print(torch.cuda.is_available())")
        argv, env, _ = backends.command("probe00", "t", [str(backends.config.python), "-c", code])
        result = subprocess.run(argv, env=env, cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        lines = result.stdout.strip().splitlines()
        self.assertTrue(lines[-2].startswith(str(ROOT / "vendor/sam3")), lines)
        self.assertEqual(lines[-1], "True")

    def test_isolation_holds_over_http_too(self):
        self.assertIn(self.b.client.get(f"/api/projects/{self.pa}").status_code, (404, 422))
        self.assertEqual(self.a.client.get(f"/api/projects/{self.pa}").json()["name"], "A")


if __name__ == "__main__":
    unittest.main()
