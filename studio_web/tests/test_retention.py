"""T11: deleting projects and workspaces, expiry, crash-safe retries, job-start disk headroom."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from studio_web import app as app_module
from studio_web.app import create_app
from studio_web.auth.sessions import SESSION_COOKIE, Recovery
from studio_web.services import retention
from studio_web.tests.test_gateway import Browser, make_config
from studio_web.tests.test_uploads import photo


class Retention(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="m4ml-ret-")
        cls.home = Path(cls.temp.name) / "web"
        cls.app = create_app(make_config(cls.home, STUDIO_WEB_MAX_ACTIVE_SESSIONS="3"))
        cls.addClassCleanup(cls.stop_all)

    @classmethod
    def stop_all(cls):
        with cls.app.state.db.connect() as db:
            ids = [r["session_id"] for r in db.execute("SELECT session_id FROM backends")]
        for sid in ids:
            cls.app.state.backends.stop(sid)
        cls.temp.cleanup()

    def setUp(self):
        # many short-lived browsers here: lift the per-address issuance limit for this class
        patcher = mock.patch("studio_web.auth.sessions.ISSUE_PER_HOUR", 1000)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.made = []

    def tearDown(self):
        for b in self.made:  # free the slots for the next test
            session = self.app.state.sessions.lookup(b.client.cookies.get(SESSION_COOKIE))
            if session:
                retention.delete_session(self.app.state.db, self.app.state.backends, self.app.state.slots, session.id)

    def browser(self):
        b = Browser(self.app)
        r = b.open()
        self.assertEqual(r.json()["slot"], "active", r.text)
        self.made.append(b)
        return b

    def sid(self, b):
        return self.app.state.sessions.lookup(b.client.cookies.get(SESSION_COOKIE)).id

    def folder(self, b):
        return self.app.state.backends.session_dir(self.sid(b))

    def project(self, b, name="삭제 시험"):
        pid = b.write("POST", "/api/projects", json={"name": name, "input_mode": "images"}).json()["id"]
        r = b.write("POST", f"/api/projects/{pid}/images", files={"file": ("a.jpg", photo(size=(320, 240)), "image/jpeg")})
        self.assertEqual(r.status_code, 200, r.text)
        return pid

    def test_1_delete_project_removes_files_and_records(self):
        a = self.browser()
        pid = self.project(a)
        folder = self.folder(a) / "data/projects" / pid
        self.assertTrue(folder.is_dir())
        self.assertEqual(a.client.delete(f"/api/projects/{pid}", headers={"origin": "https://127.0.0.1"}).status_code, 403)  # CSRF
        r = a.write("DELETE", f"/api/projects/{pid}")
        self.assertEqual(r.json(), {"deleted": True})
        self.assertFalse(folder.exists())
        self.assertFalse(any(p.name.startswith(".deleting-") for p in folder.parent.iterdir()))
        self.assertNotIn(pid, [p["id"] for p in a.client.get("/api/projects").json()])
        self.assertIn(a.client.get(f"/api/projects/{pid}").status_code, (404, 422))
        self.assertEqual(a.write("DELETE", f"/api/projects/{pid}").json(), {"deleted": True})  # idempotent

    def test_2_other_session_cannot_delete(self):
        a, b = self.browser(), self.browser()
        pid = self.project(a, "남의 것")
        self.assertEqual(b.write("DELETE", f"/api/projects/{pid}").json(), {"deleted": True})  # nothing to delete there
        self.assertEqual(a.client.get(f"/api/projects/{pid}").json()["name"], "남의 것")
        self.assertTrue((self.folder(a) / "data/projects" / pid).is_dir())
        a.write("DELETE", f"/api/projects/{pid}")

    def test_3_running_work_that_does_not_stop_blocks_deletion(self):
        a = self.browser()
        pid = self.project(a, "작업 중")
        # Simulate a job the cancel request cannot stop (no worker process behind it).
        from studio.store import Store
        store = Store(self.folder(a) / "data")
        store.update(pid, lambda d: d["stages"].update(colmap="running"))
        store.new_job(pid, "colmap", {})
        with mock.patch.object(app_module, "CANCEL_WAIT_SECONDS", 1):
            r = a.write("DELETE", f"/api/projects/{pid}")
        self.assertEqual(r.status_code, 409)
        self.assertTrue((self.folder(a) / "data/projects" / pid).is_dir())
        job = store.active(pid)
        self.assertEqual(job["cancel_requested"], 1)  # the gateway did ask the job to stop

    def test_4_delete_workspace(self):
        a = self.browser()
        pid = self.project(a)
        sid, folder = self.sid(a), self.folder(a)
        old_cookie = a.client.cookies.get(SESSION_COOKIE)
        token = a.write("POST", "/api/web/session/recovery").json()["token"]
        backend = self.app.state.backends.registered(sid)
        r = a.write("DELETE", "/api/web/session")
        self.assertEqual(r.json(), {"deleted": True, "complete": True})
        self.assertFalse(folder.exists())
        self.assertIsNone(self.app.state.backends.registered(sid))
        self.assertFalse(Path(backend.socket).exists())
        self.assertIsNone(self.app.state.sessions.lookup(old_cookie))
        self.assertIsNone(Recovery(self.app.state.db).redeem(token))
        self.assertFalse(self.app.state.slots.holds(sid))
        with self.app.state.db.connect() as db:
            row = dict(db.execute("SELECT state, token_hash, csrf FROM sessions WHERE id=?", (sid,)).fetchone())
        self.assertEqual(row["state"], "deleted")
        self.assertEqual(row["csrf"], "")
        self.assertNotIn(pid, json.dumps(row))

    def test_5_expiry_and_crash_recovery(self):
        a, b = self.browser(), self.browser()
        self.project(a, "만료")
        sid_a, sid_b = self.sid(a), self.sid(b)
        folder_a = self.folder(a)
        with self.app.state.db.connect() as db:
            db.execute("UPDATE sessions SET expires=? WHERE id=?", (time.time() - 1, sid_a))
        # a crash right after marking b for deletion: the next sweep must finish it
        retention.mark_deleting(self.app.state.db, sid_b)
        self.assertEqual(b.client.get("/api/projects").status_code, 401)  # already unusable
        done = retention.sweep(self.app.state.db, self.app.state.backends, self.app.state.slots)
        self.assertEqual(set(done), {sid_a, sid_b})
        self.assertFalse(folder_a.exists())
        self.assertEqual(a.client.get("/api/projects").status_code, 401)
        self.assertEqual(retention.sweep(self.app.state.db, self.app.state.backends, self.app.state.slots), [])

    def test_7_retried_upload_is_not_stored_twice(self):
        a = self.browser()
        pid = a.write("POST", "/api/projects", json={"name": "재시도", "input_mode": "images"}).json()["id"]
        data = photo(size=(330, 250))
        first = a.write("POST", f"/api/projects/{pid}/images", files={"file": ("a.jpg", data, "image/jpeg")})
        again = a.write("POST", f"/api/projects/{pid}/images", files={"file": ("a.jpg", data, "image/jpeg")})
        self.assertEqual((first.status_code, again.status_code), (200, 200))
        self.assertEqual(again.headers.get("x-upload-replay"), "1")
        self.assertEqual(len(again.json()["images"]), 1)
        snapshots = list((self.folder(a) / "data/projects" / pid / "input/snapshots").glob("*.original"))
        self.assertEqual(len(snapshots), 1)

    def test_6_jobs_need_disk_headroom(self):
        from studio_web.security import limits
        a = self.browser()
        pid = self.project(a, "공간 부족")
        with mock.patch.object(limits, "SESSION_BYTES", 1):
            r = a.write("POST", f"/api/projects/{pid}/import-complete")
        self.assertEqual(r.status_code, 413)
        self.assertIn("저장 용량", r.json()["detail"])
        with mock.patch.object(limits, "MIN_FREE_BYTES", 10**15):
            r = a.write("POST", f"/api/projects/{pid}/jobs/train", json={"confirmed": True})
        self.assertEqual(r.status_code, 413)


if __name__ == "__main__":
    unittest.main()


class RecordPruning(unittest.TestCase):
    def test_operational_records_older_than_30_days_are_removed(self):
        from studio_web.persistence.db import Database
        from studio_web.auth.sessions import Sessions
        with tempfile.TemporaryDirectory() as d:
            db = Database(Path(d) / "g.sqlite")
            sessions = Sessions(db, 7)
            old, _ = sessions.create()
            fresh, _ = sessions.create()
            now = time.time()
            ancient = now - 31 * 86400
            with db.connect() as c:
                c.execute("UPDATE sessions SET state='deleted', last_seen=? WHERE id=?", (ancient, old.id))
                c.execute("INSERT INTO audit(at, session_id, event) VALUES (?,?,?)", (ancient, old.id, "old event"))
                c.execute("INSERT INTO audit(at, session_id, event) VALUES (?,?,?)", (now, fresh.id, "new event"))
                c.execute("INSERT INTO gpu_leases(id, session_id, project_id, kind, route, state, created, ended) "
                          "VALUES ('l1', ?, 'p', 'batch', '/r', 'completed', ?, ?)", (fresh.id, ancient, ancient))
                c.execute("INSERT INTO issuance(client, at) VALUES ('1.2.3.4', ?)", (ancient,))
            counts = retention.prune_records(db, now)
            self.assertEqual(counts, {"audit": 1, "gpu_leases": 1, "issuance": 1, "sessions": 1})
            with db.connect() as c:
                events = [r[0] for r in c.execute("SELECT event FROM audit")]
                self.assertNotIn("old event", events)
                self.assertIn("new event", events)  # recent records (incl. "session created") stay
                self.assertEqual(c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1)
