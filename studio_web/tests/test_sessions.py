"""T09: anonymous sessions, recovery links, issuance limits, atomic slots and the queue."""

import tempfile
import threading
import time
import unittest
from pathlib import Path

from studio_web.auth.sessions import SESSION_COOKIE, ISSUE_PER_HOUR, Recovery, Sessions, digest, issuance_allowed
from studio_web.auth.slots import IDLE_SECONDS, QUEUE_MAX, QUEUE_STALE_SECONDS, Slots
from studio_web.persistence.db import Database

ORIGIN = "https://127.0.0.1"


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "g.sqlite")
        self.sessions = Sessions(self.db, 7)

    def tearDown(self):
        self.temp.cleanup()

    def new(self, n):
        return [self.sessions.create()[0].id for _ in range(n)]


class SlotTests(Base):
    def test_default_three_then_fifo_queue_then_full(self):
        s = self.new(6)
        slots = Slots(self.db, 3)
        self.assertTrue(all(slots.admit(x).active for x in s[:3]))
        self.assertEqual(slots.admit(s[3]).position, 1)
        self.assertEqual(slots.admit(s[4]).position, 2)
        self.assertTrue(slots.admit(s[5]).full)
        self.assertEqual(QUEUE_MAX, 2)
        slots.release(s[0])
        self.assertFalse(slots.admit(s[4]).active)  # no overtaking: s[3] arrived first
        self.assertTrue(slots.admit(s[3]).active)
        self.assertEqual(slots.admit(s[4]).position, 1)

    def test_stale_queue_entries_expire(self):
        s = self.new(5)
        slots = Slots(self.db, 3)
        now = time.time()
        for x in s[:3]:
            slots.admit(x, now)
        slots.admit(s[3], now)
        self.assertEqual(slots.admit(s[4], now + QUEUE_STALE_SECONDS + 1).position, 1)  # s[3] stopped polling

    def test_hard_ceiling_four_whatever_is_configured(self):
        with self.assertRaises(ValueError):
            Slots(self.db, 5)
        s = self.new(8)
        slots = Slots(self.db, 4)
        results = [slots.admit(x).active for x in s]
        self.assertEqual(sum(results), 4)
        slots.max_active = 9  # even a later bad assignment cannot exceed the ceiling
        self.assertFalse(slots.admit(s[4]).active)  # s[4] is first in the queue
        self.assertEqual(slots.active_count(), 4)

    def test_concurrent_admission_never_overfills(self):
        s = self.new(20)
        slots = Slots(self.db, 3)
        barrier, results = threading.Barrier(20), []

        def go(x):
            barrier.wait()
            results.append(slots.admit(x).active)

        threads = [threading.Thread(target=go, args=(x,)) for x in s]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(results), 3)
        self.assertEqual(slots.active_count(), 3)

    def test_idle_detection(self):
        s = self.new(2)
        slots = Slots(self.db, 3)
        now = time.time()
        slots.admit(s[0], now - IDLE_SECONDS - 5)
        slots.admit(s[1], now)
        self.assertEqual(slots.idle(now), [s[0]])


class RecoveryTests(Base):
    def test_link_moves_the_workspace_once_and_rotates_the_cookie(self):
        session, old_secret = self.sessions.create()
        recovery = Recovery(self.db)
        token = recovery.issue(session)
        with self.db.connect() as db:
            stored = [tuple(r) for r in db.execute("SELECT * FROM recovery")]
        self.assertNotIn(token, repr(stored))
        self.assertIn(digest(token), repr(stored))
        moved, new_secret = recovery.redeem(token)
        self.assertEqual(moved.id, session.id)
        self.assertNotEqual(moved.csrf, session.csrf)
        self.assertIsNone(self.sessions.lookup(old_secret))  # old browser is signed out
        self.assertEqual(self.sessions.lookup(new_secret).id, session.id)
        self.assertIsNone(recovery.redeem(token))  # one use only

    def test_new_link_replaces_old_and_expired_or_forged_fail(self):
        session, _ = self.sessions.create()
        recovery = Recovery(self.db)
        first, second = recovery.issue(session), recovery.issue(session)
        self.assertIsNone(recovery.redeem(first))
        self.assertIsNone(recovery.redeem("forged"))
        self.assertIsNone(recovery.redeem("x" * 500))
        with self.db.connect() as db:
            db.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
        self.assertIsNone(recovery.redeem(second))


class IssuanceTests(Base):
    def test_per_client_hourly_limit(self):
        now = time.time()
        self.assertTrue(all(issuance_allowed(self.db, "1.2.3.4", now) for _ in range(ISSUE_PER_HOUR)))
        self.assertFalse(issuance_allowed(self.db, "1.2.3.4", now))
        self.assertTrue(issuance_allowed(self.db, "5.6.7.8", now))
        self.assertTrue(issuance_allowed(self.db, "1.2.3.4", now + 3601))


class GatewaySessions(unittest.TestCase):
    """Real gateway + real session backends (STUDIO_WEB_MAX_ACTIVE_SESSIONS=2 to keep it short)."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from studio_web.app import create_app
        from studio_web.tests.test_gateway import Browser, make_config

        cls.TestClient, cls.Browser = TestClient, Browser
        cls.temp = tempfile.TemporaryDirectory(prefix="m4ml-sess-")
        cls.app = create_app(make_config(Path(cls.temp.name) / "web"))
        cls.addClassCleanup(cls.stop_all)

    @classmethod
    def stop_all(cls):
        with cls.app.state.db.connect() as db:
            ids = [r["session_id"] for r in db.execute("SELECT session_id FROM backends")]
        for sid in ids:
            cls.app.state.backends.stop(sid)
        cls.temp.cleanup()

    def sid(self, browser):
        return self.app.state.sessions.lookup(browser.client.cookies.get(SESSION_COOKIE)).id

    def test_1_queue_then_admission_after_release(self):
        a, b, c = (self.Browser(self.app) for _ in range(3))
        self.assertEqual(a.open().json()["slot"], "active")
        self.assertEqual(b.open().json()["slot"], "active")
        body = c.open().json()
        self.assertEqual((body["slot"], body["position"]), ("queued", 1))
        r = c.client.get("/api/projects")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.headers["x-queue-position"], "1")
        self.assertEqual(c.client.get("/api/web/queue").json()["slot"], "queued")
        self.app.state.backends.stop(self.sid(a))
        self.app.state.slots.release(self.sid(a))
        self.assertEqual(c.client.get("/api/web/queue").json()["slot"], "active")
        self.assertEqual(c.client.get("/api/projects").status_code, 200)
        type(self).b, type(self).c = b, c

    def test_2_recovery_link_over_http(self):
        b = self.b
        pid = b.write("POST", "/api/projects", json={"name": "옮길 작업", "input_mode": "images"}).json()["id"]
        self.assertEqual(b.client.post("/api/web/session/recovery", headers={"origin": ORIGIN}).status_code, 403)
        token = b.write("POST", "/api/web/session/recovery").json()["token"]
        other = self.TestClient(self.app, base_url=ORIGIN)
        self.assertEqual(other.post("/api/web/session/recover", json={"token": token}).status_code, 403)  # no Origin
        r = other.post("/api/web/session/recover", json={"token": token}, headers={"origin": ORIGIN})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn(pid, [p["id"] for p in other.get("/api/projects").json()])
        self.assertEqual(b.client.get("/api/projects").status_code, 401)  # the old browser lost it
        again = self.TestClient(self.app, base_url=ORIGIN)
        self.assertEqual(again.post("/api/web/session/recover", json={"token": token}, headers={"origin": ORIGIN}).status_code, 404)

    def test_3_recover_page_is_served_without_token_in_server_path(self):
        from studio_web import config as config_module
        if not (config_module.ROOT / "frontend/dist/index.html").is_file():
            self.skipTest("frontend not built")
        r = self.TestClient(self.app, base_url=ORIGIN).get("/recover")
        self.assertEqual(r.status_code, 200)
        self.assertIn('content="web"', r.text)

    def test_4_issuance_limit_and_spoofed_cloudflare_header(self):
        made = 0
        for _ in range(ISSUE_PER_HOUR + 2):
            client = self.TestClient(self.app, base_url=ORIGIN)
            r = client.post("/api/web/session", headers={"origin": ORIGIN, "cf-connecting-ip": f"10.0.0.{made}"})
            if r.status_code == 429:
                break
            made += 1
        # earlier tests already used part of the budget of this client address ("testclient")
        self.assertLessEqual(made, ISSUE_PER_HOUR)
        self.assertEqual(r.status_code, 429)


if __name__ == "__main__":
    unittest.main()


class NoWritePerRequest(Base):
    """Regression (T17): every request used to commit two writes (~120 ms on this disk)."""

    def test_active_session_requests_do_not_write(self):
        session, secret = self.sessions.create()
        slots = Slots(self.db, 3)
        slots.admit(session.id)
        mark = time.time() - 5  # recent, but distinguishable from a fresh write
        with self.db.connect() as db:
            db.execute("UPDATE sessions SET last_seen=? WHERE id=?", (mark, session.id))
            db.execute("UPDATE slots SET heartbeat=? WHERE session_id=?", (mark, session.id))
        for _ in range(20):
            self.assertIsNotNone(self.sessions.lookup(secret))
            self.assertTrue(slots.admit(session.id).active)
        with self.db.connect() as db:
            self.assertEqual(db.execute("SELECT last_seen FROM sessions WHERE id=?", (session.id,)).fetchone()[0], mark)
            self.assertEqual(db.execute("SELECT heartbeat FROM slots WHERE session_id=?", (session.id,)).fetchone()[0], mark)

    def test_heartbeat_and_activity_still_recorded_now_and_then(self):
        session, secret = self.sessions.create()
        slots = Slots(self.db, 3)
        now = time.time()
        slots.admit(session.id, now - 3600)
        slots.admit(session.id, now)  # stale heartbeat -> refreshed
        self.assertEqual(slots.idle(now), [])
        with self.db.connect() as db:
            db.execute("UPDATE sessions SET last_seen=? WHERE id=?", (now - 3600, session.id))
        self.sessions.lookup(secret)
        with self.db.connect() as db:
            self.assertGreater(db.execute("SELECT last_seen FROM sessions WHERE id=?", (session.id,)).fetchone()[0], now - 5)
