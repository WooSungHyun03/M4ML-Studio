"""T21: Turnstile Siteverify (stub server), CSP, rate limits, proxy-header trust boundary."""

import tempfile
import threading
import time
import unittest
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form
from fastapi.testclient import TestClient

from studio_web import config as config_module
from studio_web.app import create_app
from studio_web.auth.sessions import SESSION_COOKIE
from studio_web.security import turnstile
from studio_web.security.rate_limit import RateLimiter

ORIGIN = "https://127.0.0.1"
SECRET = "test-turnstile-secret"
received = []
stub = FastAPI()


@stub.post("/siteverify")
async def siteverify(secret: str = Form(...), response: str = Form(...), remoteip: str = Form(None), idempotency_key: str = Form(None)):
    received.append({"secret": secret, "response": response, "remoteip": remoteip})
    if secret != SECRET:
        return {"success": False, "error-codes": ["invalid-input-secret"]}
    table = {
        "good": {"success": True, "hostname": "web.example.test", "action": "session"},
        "badhost": {"success": True, "hostname": "evil.example", "action": "session"},
        "badaction": {"success": True, "hostname": "web.example.test", "action": "login"},
    }
    return table.get(response.split("-")[0], {"success": False, "error-codes": ["invalid-input-response"]})


class Turnstile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = uvicorn.Server(uvicorn.Config(stub, host="127.0.0.1", port=0, log_level="error"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        while not cls.server.started:
            time.sleep(0.02)
        port = cls.server.servers[0].sockets[0].getsockname()[1]
        cls.temp = tempfile.TemporaryDirectory(prefix="m4ml-ts-")
        secret = Path(cls.temp.name) / "turnstile"
        secret.write_text(SECRET + "\n")
        secret.chmod(0o600)
        cls.env = {"STUDIO_WEB_HOME": str(Path(cls.temp.name) / "web"), "STUDIO_WEB_TURNSTILE_SITEKEY": "0x4AAA-site",
                   "STUDIO_WEB_TURNSTILE_SECRET_FILE": str(secret), "STUDIO_WEB_PUBLIC_HOST": "web.example.test",
                   "STUDIO_WEB_TURNSTILE_VERIFY_URL": f"http://127.0.0.1:{port}/siteverify"}
        cls.app = create_app(config_module.load(cls.env))
        cls.addClassCleanup(cls.cleanup)

    @classmethod
    def cleanup(cls):
        cls.server.should_exit = True
        cls.thread.join(5)
        cls.temp.cleanup()

    def open(self, token=None):
        client = TestClient(self.app, base_url=ORIGIN)
        r = client.post("/api/web/session", headers={"origin": ORIGIN}, json={"turnstile": token} if token else None)
        return client, r

    def test_without_a_token_no_session(self):
        client, r = self.open()
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.headers["x-turnstile"], "required")
        self.assertIsNone(client.cookies.get(SESSION_COOKIE))

    def test_good_token_once_then_replay_refused(self):
        token = f"good-{time.time()}"
        client, r = self.open(token)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNotNone(client.cookies.get(SESSION_COOKIE))
        self.assertEqual(received[-1]["secret"], SECRET)  # the secret goes only to Siteverify
        self.assertEqual(received[-1]["response"], token)
        _, again = self.open(token)
        self.assertEqual(again.status_code, 403)
        # an existing session does not need a new token
        self.assertEqual(client.post("/api/web/session", headers={"origin": ORIGIN}).status_code, 200)

    def test_wrong_hostname_action_or_rejected_token(self):
        for token in (f"badhost-{time.time()}", f"badaction-{time.time()}", f"nonsense-{time.time()}", "x" * 3000):
            _, r = self.open(token)
            self.assertEqual(r.status_code, 403, token[:20])

    def test_refusal_reason_is_logged_without_token_or_secret(self):
        token = f"nonsense-{time.time()}"
        with self.assertLogs("studio_web.gateway", "WARNING") as logs:
            _, r = self.open(token)
        self.assertEqual(r.status_code, 403)
        self.assertIn("rejected:invalid-input-response", logs.output[0])
        self.assertNotIn(token, logs.output[0])
        self.assertNotIn(SECRET, logs.output[0])

    def test_unreachable_siteverify_refuses(self):
        app = create_app(config_module.load({**self.env, "STUDIO_WEB_HOME": self.env["STUDIO_WEB_HOME"] + "2",
                                             "STUDIO_WEB_TURNSTILE_VERIFY_URL": "http://127.0.0.1:9/siteverify"}))
        r = TestClient(app, base_url=ORIGIN).post("/api/web/session", headers={"origin": ORIGIN}, json={"turnstile": f"good-{time.time()}"})
        self.assertEqual(r.status_code, 403)

    def test_page_carries_the_site_key_and_csp_allows_only_cloudflare(self):
        if not (config_module.ROOT / "frontend/dist/index.html").is_file():
            self.skipTest("frontend not built")
        r = TestClient(self.app, base_url=ORIGIN).get("/")
        self.assertIn('name="m4ml-turnstile" content="0x4AAA-site"', r.text)
        csp = r.headers["content-security-policy"]
        self.assertIn("script-src 'self' https://challenges.cloudflare.com", csp)
        self.assertIn("frame-src https://challenges.cloudflare.com", csp)
        self.assertNotIn(SECRET, r.text)

    def test_secret_file_required_with_site_key(self):
        with self.assertRaises(RuntimeError):
            config_module.load({"STUDIO_WEB_HOME": self.env["STUDIO_WEB_HOME"], "STUDIO_WEB_TURNSTILE_SITEKEY": "x"})


class Limits(unittest.TestCase):
    def test_sliding_window(self):
        limiter = RateLimiter({"api": (3, 60)})
        self.assertTrue(all(limiter.allow("1.2.3.4", "api", now=t) for t in (0, 1, 2)))
        self.assertFalse(limiter.allow("1.2.3.4", "api", now=3))
        self.assertTrue(limiter.allow("5.6.7.8", "api", now=3))
        self.assertTrue(limiter.allow("1.2.3.4", "api", now=61))

    def test_gateway_returns_429_and_frames_have_their_own_budget(self):
        with tempfile.TemporaryDirectory() as d:
            app = create_app(config_module.load({"STUDIO_WEB_HOME": d}))
            app.state.limiter.limits.update({"api": (5, 60), "frame": (50, 60)})
            client = TestClient(app, base_url=ORIGIN)
            codes = [client.get("/api/web/session").status_code for _ in range(7)]
            self.assertEqual(codes[:5], [200] * 5)
            self.assertEqual(codes[5:], [429, 429])
            frame = client.post("/api/projects/11111111-2222-3333-4444-555555555555/live-render/frame", json={})
            self.assertNotEqual(frame.status_code, 429)  # separate bucket (401: no session)
            self.assertEqual(client.get("/").status_code in (200, 503), True)  # the page itself is not rate limited

    def test_used_up_session_budget_does_not_lock_out_existing_workspaces(self):
        with tempfile.TemporaryDirectory() as d:
            app = create_app(config_module.load({"STUDIO_WEB_HOME": d}))
            app.state.limiter.limits.update({"session": (2, 3600)})
            owner = TestClient(app, base_url=ORIGIN)
            self.assertEqual(owner.post("/api/web/session", headers={"origin": ORIGIN}).status_code, 200)
            # new browsers from the same address (no cookie each time): new workspaces stay limited
            codes = [TestClient(app, base_url=ORIGIN).post("/api/web/session", headers={"origin": ORIGIN}).status_code
                     for _ in range(3)]
            self.assertEqual(codes, [200, 429, 429])
            # the existing workspace still loads (the page asks POST /api/web/session on every load)
            self.assertEqual(owner.post("/api/web/session", headers={"origin": ORIGIN}).status_code, 200)

    def test_spoofed_cloudflare_header_is_ignored_unless_from_the_local_tunnel(self):
        with tempfile.TemporaryDirectory() as d:
            for trust in ("0", "1"):
                app = create_app(config_module.load({"STUDIO_WEB_HOME": f"{d}/{trust}", "STUDIO_WEB_TRUST_CLOUDFLARE": trust}))
                app.state.limiter.limits.update({"api": (2, 60)})
                client = TestClient(app, base_url=ORIGIN)  # its peer address is "testclient", not loopback
                codes = [client.get("/api/web/session", headers={"cf-connecting-ip": f"10.0.0.{i}"}).status_code for i in range(3)]
                self.assertEqual(codes[-1], 429, f"trust={trust}: a forged header must not create new budgets")


class NoWebSockets(unittest.TestCase):
    """ADR-WEB-007 keeps live rendering on HTTP: no WebSocket handshake is accepted anywhere,
    with or without a valid session (so there is no WS path that skips the HTTP checks)."""

    def test_every_websocket_handshake_is_refused(self):
        from starlette.websockets import WebSocketDisconnect
        with tempfile.TemporaryDirectory() as d:
            client = TestClient(create_app(config_module.load({"STUDIO_WEB_HOME": d})), base_url=ORIGIN)
            client.post("/api/web/session", headers={"origin": ORIGIN}).raise_for_status()
            self.assertTrue(client.cookies.get(SESSION_COOKIE))
            pid = "11111111-2222-3333-4444-555555555555"
            for url in ("/", "/ws", "/api/ws", f"/api/projects/{pid}/events", f"/api/projects/{pid}/live-render/frame",
                        "/api/web/session"):
                with self.assertRaises(WebSocketDisconnect, msg=url):
                    with client.websocket_connect(url, headers={"origin": ORIGIN}) as ws:
                        ws.receive_text()


if __name__ == "__main__":
    unittest.main()


class NoAdminOverHttp(unittest.TestCase):
    def test_admin_is_not_reachable_over_http(self):
        with tempfile.TemporaryDirectory() as d:
            client = TestClient(create_app(config_module.load({"STUDIO_WEB_HOME": d})), base_url=ORIGIN)
            for url in ("/admin", "/api/admin", "/api/web/admin", "/api/admin/status", "/api/web/maintenance"):
                self.assertEqual(client.get(url).status_code, 404, url)
                self.assertEqual(client.post(url, headers={"origin": ORIGIN}).status_code, 404, url)
