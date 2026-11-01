"""Gateway with real session backends (T06): authorisation, CSRF/Origin, policy, redaction,
cross-session isolation over HTTP, re-adoption after a gateway restart.

Backends are real `studio.api` processes started by the gateway; no GPU work is run here.
"""

import json
import os
import socket
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from studio_web import config as config_module
from studio_web.app import create_app
from studio_web.auth.sessions import CSRF_COOKIE, SESSION_COOKIE
from studio_web.security import limits, redact

ORIGIN = "https://127.0.0.1"


def make_config(home: Path, **extra):
    env = {"STUDIO_WEB_HOME": str(home), "STUDIO_WEB_MAX_ACTIVE_SESSIONS": "2", **extra}
    return config_module.load(env)


class Browser:
    """One browser: its own cookie jar, the page's own Origin."""

    def __init__(self, app):
        self.client = TestClient(app, base_url=ORIGIN)

    def open(self):
        r = self.client.post("/api/web/session", headers={"origin": ORIGIN})
        assert r.status_code == 200, r.text
        return r

    @property
    def csrf(self):
        return self.client.cookies.get(CSRF_COOKIE)

    def write(self, method, url, **kw):
        headers = {"origin": ORIGIN, "x-csrf-token": self.csrf, **kw.pop("headers", {})}
        return self.client.request(method, url, headers=headers, **kw)


class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="m4ml-gw-")
        cls.home = Path(cls.temp.name) / "web"
        cls.app = create_app(make_config(cls.home))
        cls.addClassCleanup(cls.stop_all)
        cls.a, cls.b = Browser(cls.app), Browser(cls.app)
        cls.a.open()
        cls.b.open()

    @classmethod
    def stop_all(cls):
        # Backends outlive the gateway by design, so the test must stop them itself.
        with cls.app.state.db.connect() as db:
            ids = [r["session_id"] for r in db.execute("SELECT session_id FROM backends")]
        for sid in ids:
            cls.app.state.backends.stop(sid)
        cls.temp.cleanup()

    def test_01_cookies_are_host_only_secure_and_session_is_httponly(self):
        r = Browser(self.app).open()
        cookies = r.headers.get_list("set-cookie")
        session = next(c for c in cookies if c.startswith(SESSION_COOKIE + "="))
        csrf = next(c for c in cookies if c.startswith(CSRF_COOKIE + "="))
        for c in (session, csrf):
            self.assertIn("Secure", c)
            self.assertIn("Path=/", c)
            self.assertNotIn("Domain=", c)
        self.assertIn("HttpOnly", session)
        self.assertNotIn("HttpOnly", csrf)
        # the database keeps only a hash of the cookie secret
        secret = session.split("=", 1)[1].split(";", 1)[0]
        with self.app.state.db.connect() as db:
            rows = [tuple(r) for r in db.execute("SELECT * FROM sessions")]
        self.assertNotIn(secret, json.dumps(rows))

    def test_02_session_creation_needs_same_origin(self):
        client = TestClient(self.app, base_url=ORIGIN)
        self.assertEqual(client.post("/api/web/session").status_code, 403)
        self.assertEqual(client.post("/api/web/session", headers={"origin": "https://evil.example"}).status_code, 403)

    def test_03_no_session_no_access(self):
        client = TestClient(self.app, base_url=ORIGIN)
        for url in ("/api/projects", "/api/health", "/api/about", f"/api/projects/{'0'*8}-0000-0000-0000-{'0'*12}"):
            self.assertEqual(client.get(url).status_code, 401, url)
        client.cookies.set(SESSION_COOKIE, "forged-secret", domain="127.0.0.1")
        self.assertEqual(client.get("/api/projects").status_code, 401)

    def test_04_writes_need_csrf_and_origin(self):
        body = {"name": "csrf", "input_mode": "images"}
        self.assertEqual(self.a.client.post("/api/projects", json=body, headers={"origin": ORIGIN}).status_code, 403)
        self.assertEqual(self.a.client.post("/api/projects", json=body, headers={"x-csrf-token": self.a.csrf}).status_code, 403)
        self.assertEqual(self.a.client.post("/api/projects", json=body, headers={"origin": "https://evil.example", "x-csrf-token": self.a.csrf}).status_code, 403)
        self.assertEqual(self.a.write("POST", "/api/projects", json=body, headers={"x-csrf-token": "wrong"}).status_code, 403)
        # B's CSRF token with A's cookies
        self.assertEqual(self.a.client.post("/api/projects", json=body, headers={"origin": ORIGIN, "x-csrf-token": self.b.csrf}).status_code, 403)

    def test_05_project_round_trip_without_server_paths(self):
        r = self.a.write("POST", "/api/projects", json={"name": "웹 프로젝트", "input_mode": "images"})
        self.assertEqual(r.status_code, 200, r.text)
        pid = r.json()["id"]
        doc = self.a.client.get(f"/api/projects/{pid}").json()
        self.assertEqual(doc["name"], "웹 프로젝트")
        self.assertFalse(redact.contains_path(doc), doc)
        self.assertNotIn(str(self.home), json.dumps(doc))
        listing = self.a.client.get("/api/projects").json()
        self.assertIn(pid, [p["id"] for p in listing])
        self.assertNotIn(str(self.home), self.a.client.get(f"/api/projects/{pid}/assets").text)
        type(self).project_a = pid

    def test_06_other_session_cannot_see_or_touch_it(self):
        pid = self.project_a
        self.assertNotIn(pid, [p["id"] for p in self.b.client.get("/api/projects").json()])
        self.assertIn(self.b.client.get(f"/api/projects/{pid}").status_code, (404, 422))
        self.assertIn(self.b.write("PATCH", f"/api/projects/{pid}", json={"name": "stolen"}).status_code, (404, 422))
        self.assertIn(self.b.client.get(f"/api/projects/{pid}/files/raw/000001.png").status_code, (403, 404, 422))
        self.assertEqual(self.a.client.get(f"/api/projects/{pid}").json()["name"], "웹 프로젝트")

    def test_07_denied_and_unknown_routes(self):
        for method, url in [("GET", "/api/session"), ("POST", "/api/scan-folder"), ("POST", "/api/projects/from-folder"),
                            ("POST", "/api/shutdown"), ("PUT", "/api/settings/checkpoint"), ("GET", "/api/diagnostics"),
                            ("GET", "/docs"), ("GET", "/openapi.json"), ("GET", "/api/..%2fsession"),
                            ("GET", f"/api/projects/{self.project_a}/files/logs/x.log"),
                            ("POST", f"/api/projects/{self.project_a}/live-render/external")]:
            r = self.a.write(method, url, json={"path": "/etc"}) if method != "GET" else self.a.client.get(url)
            self.assertEqual(r.status_code, 404, f"{method} {url} -> {r.status_code}")

    def test_08_host_header_and_security_headers(self):
        r = self.a.client.get("/api/projects", headers={"host": "evil.example"})
        self.assertEqual(r.status_code, 400)
        r = self.a.client.get("/api/projects")
        self.assertIn("frame-ancestors 'none'", r.headers["content-security-policy"])
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")

    def test_09_summaries_hide_host_details(self):
        health = self.a.client.get("/api/health").json()
        self.assertFalse(redact.contains_path(health), health)
        self.assertNotIn("uuid", json.dumps(health))
        self.assertNotIn("runtime_path", health)
        # the workspace's own remaining quota, never the server disk's free space
        self.assertTrue(0 < health["disk_free"] <= limits.SESSION_BYTES, health["disk_free"])
        about = self.a.client.get("/api/about").json()
        self.assertTrue(about["web"])
        self.assertNotIn("install_root", about)
        self.assertEqual(self.a.client.get("/api/gpu-monitor").json()["apps"], [])
        self.assertIn("licenses", self.a.client.get("/api/engines").json())

    def test_10_errors_carry_no_paths(self):
        r = self.a.client.get(f"/api/projects/{self.project_a}/files/raw/missing.png")
        self.assertEqual(r.status_code, 404)
        self.assertFalse(redact.contains_path(r.text), r.text)
        self.assertNotIn(str(self.home), r.text)
        self.assertIn("request_id", r.json())

    def test_11_backend_refuses_direct_calls_without_its_token(self):
        backend = self.app.state.backends.registered(self.app.state.sessions.lookup(self.a.client.cookies.get(SESSION_COOKIE)).id)
        # No TCP port at all: a UNIX socket inside the session folder (0700).
        self.assertEqual(backend.port, 0)
        sock = Path(backend.socket)
        self.assertTrue(sock.is_socket())
        self.assertEqual(sock.parent.stat().st_mode & 0o077, 0)
        with backend.sync_client(timeout=5) as client:
            for url in ("/api/projects", f"/api/projects/{self.project_a}", "/api/session", "/api/health"):
                r = client.get(backend.url + url, headers={"host": "127.0.0.1"})
                self.assertEqual(r.status_code, 404, url)
                self.assertNotIn(self.project_a, r.text)
            # with the token (as the gateway does) it answers, but still refuses denied routes
            ok = client.get(backend.url + "/api/projects", headers={"host": "127.0.0.1", "x-studio-token": backend.token})
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(client.get(backend.url + "/api/session", headers={"host": "127.0.0.1", "x-studio-token": backend.token}).status_code, 404)
            self.assertEqual(client.post(backend.url + "/api/scan-folder", json={"path": "/etc"},
                                         headers={"host": "127.0.0.1", "x-studio-token": backend.token}).status_code, 404)

    def test_12_sse_is_streamed_through(self):
        # TestClient cannot end an endless stream; run the gateway as a real server instead.
        import threading
        import time as _time
        import uvicorn

        server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=0, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        while not server.started:
            _time.sleep(0.02)
        port = server.servers[0].sockets[0].getsockname()[1]
        cookie = f"{SESSION_COOKIE}={self.a.client.cookies.get(SESSION_COOKIE)}"
        try:
            with httpx.stream("GET", f"http://127.0.0.1:{port}/api/projects/{self.project_a}/events",
                              headers={"cookie": cookie}, timeout=10) as r:
                self.assertEqual(r.status_code, 200)
                self.assertIn("text/event-stream", r.headers["content-type"])
                self.assertEqual(r.headers.get("x-accel-buffering"), "no")
                first = next(r.iter_text())
                self.assertIn(":", first)
        finally:
            server.should_exit = True
            thread.join(10)

    def test_13_ui_is_served_in_web_mode(self):
        if not (config_module.ROOT / "frontend/dist/index.html").is_file():
            self.skipTest("frontend not built")
        r = TestClient(self.app, base_url=ORIGIN).get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn('<meta name="m4ml-platform" content="web" />', r.text)
        self.assertEqual(TestClient(self.app, base_url=ORIGIN).get("/assets/../../etc/passwd").status_code, 404)

    def test_14_active_session_limit(self):
        self.assertEqual(self.b.client.get("/api/projects").status_code, 200)  # A and B both hold a backend
        c = Browser(self.app)
        c.open()
        r = c.client.get("/api/projects")  # a third backend with STUDIO_WEB_MAX_ACTIVE_SESSIONS=2
        self.assertEqual(r.status_code, 503)
        self.assertIn("이용자가 많습니다", r.json()["detail"])

    def test_15_gateway_restart_readopts_running_backends(self):
        sid = self.app.state.sessions.lookup(self.a.client.cookies.get(SESSION_COOKIE)).id
        before = self.app.state.backends.registered(sid)
        restarted = create_app(make_config(self.home))
        again = TestClient(restarted, base_url=ORIGIN, cookies=dict(self.a.client.cookies))
        self.assertIn(self.project_a, [p["id"] for p in again.get("/api/projects").json()])
        self.assertEqual(restarted.state.backends.registered(sid).pid, before.pid)


class ConfigTests(unittest.TestCase):
    def test_hard_ceiling_and_required_home(self):
        with tempfile.TemporaryDirectory() as d:
            for bad in ("0", "5", "9"):
                with self.assertRaises(RuntimeError):
                    config_module.load({"STUDIO_WEB_HOME": d, "STUDIO_WEB_MAX_ACTIVE_SESSIONS": bad})
            self.assertEqual(config_module.load({"STUDIO_WEB_HOME": d}).max_active_sessions, 3)
            self.assertEqual(config_module.load({"STUDIO_WEB_HOME": d, "STUDIO_WEB_MAX_ACTIVE_SESSIONS": "4"}).max_active_sessions, 4)
        with self.assertRaises(RuntimeError):
            config_module.load({})
        with self.assertRaises(RuntimeError):
            config_module.load({"STUDIO_WEB_HOME": str(Path.home())})


class BackendWebMode(unittest.TestCase):
    def test_backend_refuses_to_start_without_its_own_data_and_token(self):
        import subprocess, sys
        env = {k: v for k, v in os.environ.items() if k not in ("STUDIO_DATA", "STUDIO_TOKEN")}
        env.update(STUDIO_MODE="web", HOME=tempfile.mkdtemp())
        r = subprocess.run([sys.executable, "-c", "import studio.api"], cwd=config_module.ROOT, env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("STUDIO_DATA", r.stderr)
        self.assertFalse((Path(env["HOME"]) / ".local/share").exists())

    def test_backend_denied_set_matches_the_gateway_policy(self):
        from studio import api
        from studio_web.security.route_policy import ROUTES, Access
        self.assertEqual(set(api.WEB_DENIED), {(r.method, r.template) for r in ROUTES if r.access is Access.DENY})


if __name__ == "__main__":
    unittest.main()
