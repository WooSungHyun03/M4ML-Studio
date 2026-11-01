"""T13/T14: GPU leases — one owner, FIFO batch queue, verified release, external users, restart."""

import asyncio
import fcntl
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from studio_web.auth.sessions import Sessions
from studio_web.persistence.db import Database
from studio_web.runtime import gpu_leases as gl

JOB = "/api/projects/{project_id}/jobs/{stage}"
CLICK = "/api/projects/{project_id}/prompt"
HOLD = ("import fcntl, sys, hashlib\nh = open(sys.argv[1] + '/' + hashlib.sha256(b'dev').hexdigest() + '.lock', 'a')\n"
        "fcntl.flock(h, fcntl.LOCK_EX)\nprint('HELD', flush=True)\nsys.stdin.read()\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = Database(root / "g.sqlite")
        self.sessions = Sessions(self.db, 7)
        self.locks = root / "locks"
        self.leases = gl.GpuLeases(self.db, self.locks, "dev", root / "maintenance")

    def tearDown(self):
        self.temp.cleanup()

    def new(self, n):
        return [self.sessions.create()[0].id for _ in range(n)]

    def ask(self, sid, template=JOB, body=b"{}", **kw):
        return self.leases.request(sid, "p-" + sid, template, f"/api/projects/p-{sid}/jobs/train", body, **kw)

    def external_holder(self):
        proc = subprocess.Popen([sys.executable, "-c", HOLD, str(self.locks)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.assertEqual(proc.stdout.readline().strip(), "HELD")
        self.addCleanup(lambda: (proc.stdin.close(), proc.wait(10)))
        return proc


class LeaseTests(Base):
    def test_one_owner_fifo_batch_queue_and_no_interactive_queue(self):
        a, b, c = self.new(3)
        self.assertEqual(self.ask(a).status, "granted")
        qb, qc = self.ask(b), self.ask(c)
        self.assertEqual((qb.status, qb.position), ("queued", 1))
        self.assertEqual((qc.status, qc.position), ("queued", 2))
        self.assertEqual(self.ask(b, CLICK).status, "busy")  # clicks are never queued
        self.assertEqual(self.ask(b).position, 1)  # asking again keeps the place, one entry per session
        self.assertEqual(len(self.leases.queue()), 2)

    def test_holder_is_reentrant_and_interactive_upgrades_to_batch(self):
        a, = self.new(1)
        first = self.ask(a, CLICK)
        self.assertTrue(first.new)
        again = self.ask(a, JOB)
        self.assertEqual((again.status, again.lease_id, again.new), ("granted", first.lease_id, False))
        self.assertEqual(self.leases.owner()["kind"], "batch")

    def test_release_only_after_verified_teardown_then_next_in_line(self):
        a, b, c = self.new(3)
        self.ask(a)
        self.ask(b, body=b'{"confirmed": true}')
        self.ask(c)
        self.assertFalse(self.leases.release_if_idle(holder_running=True))  # still running
        holder = self.external_holder()
        self.assertFalse(self.leases.release_if_idle(holder_running=False))  # lock still held
        holder.stdin.close(); holder.wait(10)
        self.assertTrue(self.leases.release_if_idle(holder_running=False))
        # GPU free but b and c are waiting: a newcomer must not take it first
        late = self.ask(self.new(1)[0])
        self.assertEqual((late.status, late.position), ("queued", 3))
        promoted = self.leases.promote_next()
        self.assertEqual((promoted["session_id"], promoted["body"]), (b, b'{"confirmed": true}'))
        self.assertEqual(self.leases.owner()["session_id"], b)
        self.assertEqual(self.leases.status_for(c)["queued_position"], 1)

    def test_external_gpu_user_blocks_new_work(self):
        a, = self.new(1)
        holder = self.external_holder()  # e.g. the desktop app holds the shared lock
        self.assertEqual(self.ask(a, CLICK).reason, "external")
        self.assertEqual(self.ask(a).status, "queued")
        self.assertIsNone(self.leases.promote_next())
        holder.stdin.close(); holder.wait(10)
        self.assertEqual(self.leases.promote_next()["session_id"], a)
        self.assertEqual(self.ask(self.new(1)[0], CLICK, external_busy=True).status, "busy")

    def test_queued_work_waits_for_a_lockless_external_cuda_process(self):
        # the installed desktop v1.0.0 does not take the shared lock: it is seen only as a
        # CUDA process (nvidia-smi). Found on the installed service: queued work started anyway.
        a, = self.new(1)
        self.assertEqual(self.ask(a, external_busy=True).status, "queued")
        self.assertIsNone(self.leases.promote_next(external_busy=True))
        self.assertEqual(self.leases.queue()[0]["session_id"], a)
        self.assertEqual(self.leases.promote_next(external_busy=False)["session_id"], a)

    def test_viewer_lease_does_not_turn_into_heavy_work_beside_the_desktop(self):
        a, = self.new(1)
        self.assertEqual(self.ask(a, CLICK).status, "granted")  # e.g. the live viewer
        self.assertEqual(self.ask(a, external_busy=True).reason, "external")
        self.assertEqual(self.leases.owner()["kind"], "interactive")  # still only the viewer
        self.assertEqual(self.ask(a).status, "granted")  # once the desktop is gone
        self.assertEqual(self.leases.owner()["kind"], "batch")

    def test_maintenance_mode(self):
        a, = self.new(1)
        self.leases.maintenance_flag.touch()
        self.assertEqual(self.ask(a).reason, "maintenance")
        self.assertIsNone(self.leases.promote_next())

    def test_concurrent_requests_give_exactly_one_owner(self):
        sids = self.new(10)
        barrier, results = threading.Barrier(10), []

        def go(sid):
            barrier.wait()
            results.append(self.ask(sid).status)

        threads = [threading.Thread(target=go, args=(s,)) for s in sids]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(results.count("granted"), 1)
        self.assertEqual(results.count("queued"), 9)

    def test_database_refuses_a_second_owner(self):
        a, b = self.new(2)
        self.ask(a)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.connect() as db:
                db.execute("INSERT INTO gpu_leases(id, session_id, project_id, kind, route, state, created) "
                           "VALUES ('x', ?, 'p', 'batch', '/r', 'running', 0)", (b,))

    def test_daily_budget(self):
        a, = self.new(1)
        now = time.time()
        with self.db.connect() as db:
            db.execute("INSERT INTO gpu_leases(id, session_id, project_id, kind, route, state, created, started, ended) "
                       "VALUES ('old', ?, 'p', 'batch', '/r', 'completed', ?, ?, ?)", (a, now - 9000, now - 9000, now - 1000))
        self.assertEqual(self.ask(a).reason, "budget")
        self.assertEqual(self.ask(a, CLICK).status, "granted")  # interactive work is not budgeted

    def test_restart_keeps_the_owner_and_never_restarts_work(self):
        a, b = self.new(2)
        lease = self.ask(a).lease_id
        self.ask(b)
        again = gl.GpuLeases(self.db, self.locks, "dev", self.leases.maintenance_flag)  # a new gateway process
        self.assertEqual(again.owner()["id"], lease)
        self.assertIsNone(again.promote_next())  # GPU still owned: nothing new starts
        self.assertTrue(again.release_if_idle(holder_running=False))
        self.assertEqual(again.promote_next()["session_id"], b)


class GatewayLeases(unittest.TestCase):
    """Real gateway + backends; GPU work refused by the backend (no photos), so no GPU is used."""

    @classmethod
    def setUpClass(cls):
        from studio_web.app import create_app
        from studio_web.tests.test_gateway import Browser, make_config
        cls.temp = tempfile.TemporaryDirectory(prefix="m4ml-gpu-")
        cls.app = create_app(make_config(Path(cls.temp.name) / "web", STUDIO_WEB_MAX_ACTIVE_SESSIONS="3"))
        cls.addClassCleanup(cls.stop_all)
        cls.a, cls.b = Browser(cls.app), Browser(cls.app)
        cls.a.open(); cls.b.open()
        cls.pa = cls.a.write("POST", "/api/projects", json={"name": "A", "input_mode": "images"}).json()["id"]
        cls.pb = cls.b.write("POST", "/api/projects", json={"name": "B", "input_mode": "images"}).json()["id"]

    @classmethod
    def stop_all(cls):
        with cls.app.state.db.connect() as db:
            ids = [r["session_id"] for r in db.execute("SELECT session_id FROM backends")]
        for sid in ids:
            cls.app.state.backends.stop(sid)
        cls.temp.cleanup()

    def sid(self, b):
        return self.app.state.sessions.lookup(b.client.cookies.get("__Host-m4ml_session")).id

    def test_refused_work_releases_and_queue_starts_next(self):
        leases = self.app.state.leases
        # A's job is refused by its backend (import not completed): the new lease must not stay.
        r = self.a.write("POST", f"/api/projects/{self.pa}/jobs/colmap", json={})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIsNone(leases.owner())
        # A holds the GPU (granted directly); B's batch request queues, B's click is busy.
        grant = leases.request(self.sid(self.a), self.pa, JOB, f"/api/projects/{self.pa}/jobs/train", b"{}")
        self.assertEqual(grant.status, "granted")
        q = self.b.write("POST", f"/api/projects/{self.pb}/jobs/colmap", json={})
        self.assertEqual((q.status_code, q.json()["position"]), (202, 1))
        busy = self.b.write("POST", f"/api/projects/{self.pb}/prompt", json={"session_id": "s", "prompt_revision": 1})
        self.assertEqual(busy.status_code, 503)
        self.assertEqual(self.b.client.get("/api/web/gpu").json()["queued_position"], 1)
        self.assertTrue(self.a.client.get("/api/web/gpu").json()["holding"])
        # The monitor: A has no running stage and the lock is free -> release, then B's
        # stored request is forwarded (and refused by B's backend -> lease failed, GPU free).
        run = asyncio.new_event_loop()
        try:
            run.run_until_complete(self.app.state.gpu_monitor_once())
            self.assertIsNone(leases.owner())
            run.run_until_complete(self.app.state.gpu_monitor_once())
        finally:
            run.close()
        with self.app.state.db.connect() as db:
            rows = [dict(r) for r in db.execute("SELECT session_id, state, message FROM gpu_leases ORDER BY created")]
        self.assertEqual([r["state"] for r in rows], ["failed", "completed", "failed"], rows)
        self.assertEqual(rows[2]["session_id"], self.sid(self.b))
        self.assertTrue(rows[2]["message"])  # the backend's reason, shown to B
        self.assertIsNone(leases.owner())


if __name__ == "__main__":
    unittest.main()


class StrayReaper(unittest.TestCase):
    """Left-over job processes in an idle session are stopped after the grace period;
    the session's long-lived parts are never touched."""

    def test_strays_are_stopped_and_residents_kept(self):
        from unittest import mock
        from studio_web import app as app_module
        from studio_web.app import create_app
        from studio_web.tests.test_gateway import Browser, make_config
        with tempfile.TemporaryDirectory(prefix="m4ml-stray-") as d:
            app = create_app(make_config(Path(d) / "web"))
            b = Browser(app)
            b.open()
            self.assertEqual(b.client.get("/api/projects").status_code, 200)
            sid = app.state.sessions.lookup(b.client.cookies.get("__Host-m4ml_session")).id
            backend = app.state.backends.registered(sid)
            stray = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)  # train.py"])
            resident = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", "studio.sam31_session"])
            fake_tree = [(backend.pid, backend.pid_start), (stray.pid, "x"), (resident.pid, "y")]
            try:
                with mock.patch.object(app_module, "_descendants", lambda root: fake_tree if root == backend.pid else []), \
                        mock.patch.object(app_module, "ORPHAN_GRACE_SECONDS", 0):
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(app.state.reap_strays_once())  # first sighting
                    time.sleep(0.1)
                    loop.run_until_complete(app.state.reap_strays_once())  # past the grace period
                    loop.close()
                self.assertIsNotNone(stray.wait(10))
                self.assertIsNone(resident.poll())  # the object-selection session survives
            finally:
                for p in (stray, resident):
                    if p.poll() is None:
                        p.kill()
                        p.wait()
                app.state.backends.stop(sid)
