"""Proxy layer on its own: a fake backend that leaks paths and headers on purpose."""

import threading
import time
import unittest

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.testclient import TestClient

from studio_web.runtime.backends import Backend
from studio_web.security.route_policy import match
from studio_web.streaming.proxy import forward

PID = "11111111-2222-3333-4444-555555555555"
seen = {}
fake = FastAPI()


@fake.api_route("/api/{rest:path}", methods=["GET", "POST", "PATCH"])
async def echo(request: Request, rest: str):
    seen["headers"] = dict(request.headers)
    if rest.endswith("fail-path"):
        return JSONResponse({"detail": "사진을 불러오지 못했습니다: /srv/m4ml-web/sessions/abc/data/x.png"}, status_code=422)
    if rest.endswith("fail-list"):
        return JSONResponse({"detail": [{"loc": ["body", "x"], "msg": "bad", "input": "/etc/passwd"}]}, status_code=422)
    if rest.endswith("fail-plain"):
        return JSONResponse({"detail": "실행 중인 작업을 먼저 중지하세요."}, status_code=409)
    if rest.endswith((".ply", ".glb", ".png")):
        return Response(b"ply\n", media_type="text/plain")
    if rest.endswith("live"):
        return Response(b"jpeg", media_type="image/jpeg", headers={"X-Render-Ms": "7", "X-Secret": "s", "Set-Cookie": "x=1"})
    return JSONResponse({"id": PID, "project_path": "/home/u/p", "jobs": [{"message": "실패: /tmp/abc/run.log 확인"}]})


class ProxyLayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = uvicorn.Server(uvicorn.Config(fake, host="127.0.0.1", port=0, log_level="error"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        while not cls.server.started:
            time.sleep(0.02)
        port = cls.server.servers[0].sockets[0].getsockname()[1]
        backend = Backend("s", port, "backend-secret", 0, "")
        gw = FastAPI()

        @gw.api_route("/{rest:path}", methods=["GET", "POST", "PATCH"])
        async def route(request: Request, rest: str, template: str = ""):
            r, _ = match(request.method, template)
            return await forward(request, r, backend, request.url.path)

        cls.client = TestClient(gw)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(5)

    def get(self, path, template, method="GET", **kw):
        return self.client.request(method, path, params={"template": template}, **kw)

    def test_error_details_with_paths_are_replaced(self):
        r = self.get("/api/projects/x/fail-path", f"/api/projects/{PID}", method="PATCH", json={})
        self.assertEqual(r.status_code, 422)
        self.assertNotIn("/srv", r.text)
        self.assertIn("request_id", r.json())

    def test_validation_lists_never_echo_input(self):
        r = self.get("/api/projects/x/fail-list", f"/api/projects/{PID}", method="PATCH", json={})
        self.assertEqual(r.status_code, 422)
        self.assertNotIn("/etc/passwd", r.text)

    def test_plain_errors_pass_through(self):
        r = self.get("/api/projects/x/fail-plain", f"/api/projects/{PID}", method="PATCH", json={})
        self.assertEqual(r.json()["detail"], "실행 중인 작업을 먼저 중지하세요.")

    def test_filtered_json_drops_path_keys_and_paths_in_text(self):
        r = self.get("/api/projects/x/doc", f"/api/projects/{PID}")
        body = r.json()
        self.assertNotIn("project_path", body)
        self.assertNotIn("/tmp/abc", r.text)
        self.assertIn("[서버 경로]", body["jobs"][0]["message"])

    def test_request_headers_are_rebuilt(self):
        self.get("/api/projects/x/doc", f"/api/projects/{PID}",
                 headers={"cookie": "__Host-m4ml_session=browser-secret", "x-studio-token": "forged",
                          "origin": "https://evil.example", "x-forwarded-for": "1.2.3.4"})
        h = seen["headers"]
        self.assertEqual(h["x-studio-token"], "backend-secret")
        for leaked in ("cookie", "origin", "x-forwarded-for"):
            self.assertNotIn(leaked, h)
        self.assertTrue(h["host"].startswith("127.0.0.1:"))

    def test_response_headers_are_allow_listed(self):
        r = self.get("/api/projects/x/live", f"/api/projects/{PID}/live-render/frame", method="POST", json={})
        self.assertEqual(r.headers["x-render-ms"], "7")
        self.assertNotIn("x-secret", r.headers)
        self.assertNotIn("set-cookie", r.headers)

    def test_mesh_downloads_get_their_real_type(self):
        template = f"/api/projects/{PID}/files/model.ply"
        self.assertEqual(self.get(f"/api/projects/{PID}/files/m/model.ply", template).headers["content-type"], "application/octet-stream")
        self.assertEqual(self.get(f"/api/projects/{PID}/files/m/model.GLB", template).headers["content-type"], "model/gltf-binary")
        self.assertTrue(self.get(f"/api/projects/{PID}/files/m/a.png", template).headers["content-type"].startswith("text/plain"))

    def test_body_limit(self):
        r = self.get("/api/projects/x/doc", f"/api/projects/{PID}", method="PATCH", content=b"x" * (2**20 + 1),
                     headers={"content-type": "application/json"})
        self.assertEqual(r.status_code, 413)


if __name__ == "__main__":
    unittest.main()
