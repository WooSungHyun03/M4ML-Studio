"""Contract tests for the web route policy (T01).

Run from the repository root:
  .runtime/bin/python -m unittest discover -s studio_web/tests -t .
"""

import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ.setdefault("STUDIO_DATA", tempfile.mkdtemp(prefix="m4ml-web-test-"))

from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from studio import api  # noqa: E402
from studio.store import Store  # noqa: E402
from studio_web.security.route_policy import ROUTES, Access, Rejected, match, normalise  # noqa: E402

PID = str(uuid.uuid4())
JOB = str(uuid.uuid4())

TRAVERSALS = [
    "../secret.png",
    "..%2fsecret.png",
    "..%2Fsecret.png",
    "%2e%2e/secret.png",
    "%2E%2E/secret.png",
    ".%2e/secret.png",
    "..%252fsecret.png",
    "%252e%252e/secret.png",
    "images/../../secret.png",
    "images/%2e%2e/%2e%2e/secret.png",
    "images\\..\\secret.png",
    "images%5c..%5csecret.png",
    "/etc/passwd",
    "%2fetc%2fpasswd",
    "images//secret.png",
    "images/./secret.png",
    "secret.png%00.png",
    "secret%00.png",
    "images/secret.png/",
    "images/secrét.png",
    "images/%c3%a9.png",
    "images/%ff.png",
    ".hidden.png",
    "logs/job.log",
    "settings.json",
    "runs/x/chkpnt100.pth",
    "a/b/c/d/e/f/g/h/i/j/deep.png",
]


class RouteTable(unittest.TestCase):
    def test_every_backend_route_has_exactly_one_decision(self):
        backend = {
            (method, route.path)
            for route in api.app.routes
            if isinstance(route, APIRoute)
            for method in route.methods
        }
        policy = [(r.method, r.template) for r in ROUTES]
        self.assertEqual(len(policy), len(set(policy)), "duplicate policy entries")
        self.assertEqual(backend - set(policy), set(), "backend routes without a web decision")
        self.assertEqual(set(policy) - backend, set(), "policy entries for routes that do not exist")

    def test_dangerous_routes_are_never_proxied(self):
        must_not_proxy = {
            ("GET", "/api/session"),
            ("POST", "/api/scan-folder"),
            ("POST", "/api/projects/from-folder"),
            ("POST", "/api/shutdown"),
            ("PUT", "/api/settings/checkpoint"),
            ("GET", "/api/diagnostics"),
            ("GET", "/api/engines"),
            ("GET", "/api/gpu-monitor"),
            ("GET", "/api/about"),
            ("GET", "/api/health"),
            ("POST", "/api/projects/{project_id}/live-render/external"),
            ("GET", "/api/projects/{project_id}/logs/{job_id}"),
            ("POST", "/api/projects/{project_id}/import-files"),
            ("POST", "/api/projects/{project_id}/mesh-file"),
            ("POST", "/api/projects/{project_id}/images"),
        }
        table = {(r.method, r.template): r for r in ROUTES}
        for key in must_not_proxy:
            self.assertIsNot(table[key].access, Access.PROXY, key)
            with self.assertRaises(Rejected):
                match(key[0], key[1].replace("{project_id}", PID).replace("{job_id}", JOB))

    def test_gpu_routes_are_marked(self):
        gpu = {r.template for r in ROUTES if r.gpu}
        for template in (
            "/api/projects/{project_id}/jobs/{stage}",
            "/api/projects/{project_id}/prompt",
            "/api/projects/{project_id}/live-render/start",
            "/api/projects/{project_id}/import-complete",
        ):
            self.assertIn(template, gpu)


class Matching(unittest.TestCase):
    def test_allowed_requests(self):
        cases = [
            ("GET", "/api/projects", "/api/projects"),
            ("GET", f"/api/projects/{PID}", "/api/projects/{project_id}"),
            ("POST", f"/api/projects/{PID}/jobs/train", "/api/projects/{project_id}/jobs/{stage}"),
            ("GET", f"/api/projects/{PID}/files/raw/000001.png", "/api/projects/{project_id}/files/{path:path}"),
            ("GET", f"/api/projects/{PID}/files/runs/{JOB}/mesh/fuse_post.ply", "/api/projects/{project_id}/files/{path:path}"),
            ("PUT", f"/api/projects/{PID}/masks/000003.png", "/api/projects/{project_id}/masks/{name}"),
            ("GET", "/api/help/guide", "/api/help/{name}"),
            ("GET", f"/api/projects/{PID}/training-metrics/{JOB}", "/api/projects/{project_id}/training-metrics/{job_id}"),
        ]
        for method, path, template in cases:
            route, params = match(method, path)
            self.assertEqual(route.template, template, path)
            self.assertEqual(params.get("project_id", PID), PID)

    def test_wrong_method_unknown_and_non_canonical_ids(self):
        for method, path in [
            ("DELETE", "/api/projects"),
            ("GET", f"/api/projects/{PID}/jobs/train"),
            ("POST", f"/api/projects/{PID}/jobs/shell"),
            ("GET", f"/api/projects/{PID.upper()}"),
            ("GET", "/api/projects/not-a-uuid"),
            ("GET", f"/api/projects/{PID}/files/raw/000001.json"),
            ("GET", "/api/help/../../etc/passwd"),
            ("GET", "/api/web-admin"),
            ("GET", "/docs"),
            ("GET", "/openapi.json"),
            ("PATCH", f"/api/projects/{PID}/task-settings/secrets"),
        ]:
            with self.assertRaises(Rejected, msg=f"{method} {path}"):
                match(method, path)

    def test_path_fuzz_is_rejected(self):
        for suffix in TRAVERSALS:
            with self.assertRaises(Rejected, msg=suffix):
                match("GET", f"/api/projects/{PID}/files/{suffix}")

    def test_normalise_rejects_ambiguous_forms(self):
        for raw in ["api/projects", "/api/projects?x=1", "/api/projects#x", "/" + "a" * 2050,
                    "/api/%2e%2e/session", "/api//projects", "/api/projects/"]:
            with self.assertRaises(Rejected, msg=raw):
                normalise(raw)
        self.assertEqual(normalise("/api/projects"), "/api/projects")


class BackendFileRouteFuzz(unittest.TestCase):
    """Defence in depth: the backend's own /files check must also hold for every fuzz case."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = api.store
        api.store = self.store = Store(Path(self.temp.name) / "data")
        self.project = self.store.create("fuzz")
        root = self.store.path(self.project["id"])
        (root / "raw").mkdir(exist_ok=True)
        (root / "raw/ok.png").write_bytes(b"\x89PNG-ok")
        (Path(self.temp.name) / "data/secret.png").write_bytes(b"SECRET")
        (root / "logs").mkdir(exist_ok=True)
        (root / "logs/job.log").write_text("/home/someone/private/path")
        self.client = TestClient(api.app)

    def tearDown(self):
        api.store = self.previous
        self.temp.cleanup()

    def test_backend_never_serves_outside_the_project(self):
        base = f"/api/projects/{self.project['id']}/files/"
        self.assertEqual(self.client.get(base + "raw/ok.png").status_code, 200)
        for suffix in TRAVERSALS:
            response = self.client.get(base + suffix)
            self.assertNotIn(b"SECRET", response.content, suffix)

    def test_backend_raw_http_requests(self):
        """httpx normalises '../' before sending; send the raw request line over a socket."""
        import socket
        import threading
        import uvicorn

        server = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1", port=0, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(200):
            if server.started:
                break
            __import__("time").sleep(0.02)
        port = server.servers[0].sockets[0].getsockname()[1]
        try:
            base = f"/api/projects/{self.project['id']}/files/"
            for suffix in TRAVERSALS:
                with socket.create_connection(("127.0.0.1", port), timeout=5) as conn:
                    conn.sendall(f"GET {base}{suffix} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
                                 .encode("utf-8", "surrogateescape"))
                    reply = b""
                    while chunk := conn.recv(65536):
                        reply += chunk
                # Files outside the project never leak, even with raw '../' request lines.
                self.assertNotIn(b"SECRET", reply, suffix)
        finally:
            server.should_exit = True
            thread.join(5)

    def test_backend_serves_logs_which_the_policy_must_block(self):
        # The desktop backend allows .log/.json; the web policy is what keeps them away.
        base = f"/api/projects/{self.project['id']}/files/"
        self.assertEqual(self.client.get(base + "logs/job.log").status_code, 200)
        with self.assertRaises(Rejected):
            match("GET", base + "logs/job.log")


if __name__ == "__main__":
    unittest.main()
