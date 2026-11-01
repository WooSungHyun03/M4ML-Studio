"""T22: admin tool, backup/restore, schema upgrade and rollback safety, audit hygiene."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from studio_web import admin
from studio_web import config as config_module
from studio_web.app import create_app
from studio_web.auth.sessions import SESSION_COOKIE
from studio_web.persistence import db as db_module
from studio_web.persistence.db import Database

ORIGIN = "https://127.0.0.1"
ROOT = config_module.ROOT


class Operations(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="m4ml-ops-")
        self.home = Path(self.temp.name) / "web"
        self.env = {"STUDIO_WEB_HOME": str(self.home)}
        self.patch = mock.patch.dict(os.environ, self.env)
        self.patch.start()
        self.app = create_app(config_module.load(self.env))
        self.client = TestClient(self.app, base_url=ORIGIN)
        self.client.post("/api/web/session", headers={"origin": ORIGIN}).raise_for_status()
        self.secret = self.client.cookies.get(SESSION_COOKIE)

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_status_and_maintenance(self):
        status = admin.status()
        self.assertEqual(status["schema_version"], len(db_module.MIGRATIONS))
        self.assertEqual(status["sessions"].get("active"), 1)
        self.assertFalse(status["maintenance"])
        self.assertTrue(admin.maintenance(True)["maintenance"])
        self.assertEqual(self.client.get("/api/web/ready").json()["gpu"], "maintenance")
        sid = self.app.state.sessions.lookup(self.secret).id
        self.assertEqual(self.app.state.leases.request(sid, "p", "/api/projects/{project_id}/jobs/{stage}", "/r", b"{}").reason, "maintenance")
        self.assertFalse(admin.maintenance(False)["maintenance"])

    def test_too_long_home_is_not_ready_and_is_logged(self):
        self.assertTrue(self.client.get("/api/web/ready").json()["ready"])
        deep = Path(self.temp.name) / ("d" * 90)
        app = create_app(config_module.load({"STUDIO_WEB_HOME": str(deep)}))
        client = TestClient(app, base_url=ORIGIN)
        self.assertEqual(client.get("/api/web/ready").status_code, 503)  # caught at install, not per user
        client.post("/api/web/session", headers={"origin": ORIGIN}).raise_for_status()
        with self.assertLogs("studio_web.gateway", "WARNING") as logs:
            self.assertEqual(client.get("/api/projects").status_code, 503)
        self.assertIn("not started", logs.output[0])
        self.assertNotIn(str(deep), logs.output[0])  # no server paths in the log line

    def test_backend_start_failure_reaches_the_journal(self):
        # a "runtime" that fails like a broken sandbox: its last words must reach the
        # gateway log (the operator cannot read the session folder), without session paths
        fake = Path(self.temp.name) / "broken-python"
        fake.write_text("#!/bin/sh\necho \"bwrap: Can't mount proc on /newroot/proc: Operation not permitted\"\nexit 1\n")
        fake.chmod(0o755)
        app = create_app(config_module.load({**self.env, "STUDIO_WEB_HOME": str(Path(self.temp.name) / "w2"),
                                             "STUDIO_WEB_PYTHON": str(fake)}))
        client = TestClient(app, base_url=ORIGIN)
        client.post("/api/web/session", headers={"origin": ORIGIN}).raise_for_status()
        with self.assertLogs("studio_web.backends", "WARNING") as logs:
            self.assertEqual(client.get("/api/projects").status_code, 503)
        self.assertIn("Can't mount proc", logs.output[0])
        self.assertNotIn(str(Path(self.temp.name) / "w2"), logs.output[0])

    def test_backup_restore_keeps_sessions(self):
        target = Path(self.temp.name) / "backup.sqlite"
        result = admin.backup(str(target))
        self.assertTrue(result["integrity"])
        restored_home = Path(self.temp.name) / "restored"
        restored_home.mkdir()
        os.replace(target, restored_home / "gateway.sqlite")
        app = create_app(config_module.load({"STUDIO_WEB_HOME": str(restored_home)}))
        self.assertIsNotNone(app.state.sessions.lookup(self.secret))  # the same browser keeps its workspace

    def test_old_code_refuses_a_newer_database(self):
        with self.app.state.db.connect() as conn:
            conn.execute("UPDATE schema_version SET version=?", (len(db_module.MIGRATIONS) + 1,))
        with self.assertRaises(RuntimeError):
            create_app(config_module.load(self.env))

    def test_upgrade_from_the_first_schema_keeps_data(self):
        old = Path(self.temp.name) / "old" / "gateway.sqlite"
        old.parent.mkdir()
        conn = sqlite3.connect(old)
        conn.executescript("CREATE TABLE schema_version(version INTEGER NOT NULL); INSERT INTO schema_version VALUES (1);"
                           + db_module.MIGRATIONS[0]
                           + "INSERT INTO sessions VALUES ('s1','h1','c',0,0,9999999999,'active');")
        conn.commit(); conn.close()
        db = Database(old)
        self.assertEqual(db.version(), len(db_module.MIGRATIONS))
        with db.connect() as c:
            self.assertEqual(c.execute("SELECT id FROM sessions").fetchone()[0], "s1")
            c.execute("SELECT * FROM gpu_leases")  # later tables exist

    def test_audit_contains_no_secrets(self):
        self.client.post("/api/web/session/recovery", headers={"origin": ORIGIN, "x-csrf-token": self.client.cookies.get("__Host-m4ml_csrf")})
        events = admin.audit(100)
        text = json.dumps(events)
        self.assertTrue(events)
        self.assertNotIn(self.secret, text)
        with self.app.state.db.connect() as conn:
            dump = "\n".join(conn.iterdump())
        self.assertNotIn(self.secret, dump)  # only hashes of cookie secrets are stored

    def test_cli_entry_point(self):
        r = subprocess.run([sys.executable, "-m", "studio_web.admin", "status"], cwd=ROOT, env={**os.environ, **self.env},
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("schema_version", r.stdout)
        self.assertEqual(subprocess.run([sys.executable, "-m", "studio_web.admin", "nonsense"], cwd=ROOT,
                                        env={**os.environ, **self.env}, capture_output=True).returncode, 2)

    def test_backup_script(self):
        target = Path(self.temp.name) / "backups"
        r = subprocess.run([str(ROOT / "deploy/web/scripts/backup.sh"), str(target)], cwd=ROOT,
                           env={**os.environ, **self.env, "STUDIO_WEB_PYTHON": sys.executable}, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        files = list(target.glob("gateway-*.sqlite"))
        self.assertEqual(len(files), 1)
        self.assertEqual(target.stat().st_mode & 0o077, 0)


if __name__ == "__main__":
    unittest.main()
