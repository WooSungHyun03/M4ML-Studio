"""Forward an allowed browser request to the caller's own session backend.

Headers are rebuilt, never copied: the backend sees only Host, its own token and a few
content headers. Responses are streamed (SSE, images, meshes); JSON routes with a response
filter are buffered and redacted; error bodies never carry server paths.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from studio_web.runtime.backends import Backend
from studio_web.security import redact
from studio_web.security.route_policy import Route

REQUEST_HEADERS = ("content-type", "accept", "last-event-id", "range", "if-none-match")
RESPONSE_HEADERS = ("content-type", "content-length", "content-range", "accept-ranges", "etag",
                    "last-modified", "cache-control", "x-live-state")
# Request body limits per template (bytes). Default 1 MiB.
BODY_LIMITS = {
    "/api/projects/{project_id}/masks/{name}": 16 * 2**20,
    "/api/projects/{project_id}/live-render/frame": 64 * 2**10,
}
DEFAULT_BODY_LIMIT = 2**20
# Mesh downloads: the backend guesses text/plain for .ply; the gateway states the real type.
MESH_TYPES = {".ply": "application/octet-stream", ".glb": "model/gltf-binary"}
TIMEOUT = httpx.Timeout(connect=5, read=None, write=60, pool=10)


def problem(status: int, message: str, request_id: str | None = None) -> JSONResponse:
    request_id = request_id or uuid.uuid4().hex[:12]
    return JSONResponse({"detail": message, "request_id": request_id}, status_code=status,
                        headers={"Cache-Control": "no-store", "X-Request-Id": request_id})


async def read_body(request: Request, limit: int) -> bytes | None:
    declared = request.headers.get("content-length")
    if declared and (not declared.isdigit() or int(declared) > limit):
        return None
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


async def forward(request: Request, route: Route, backend: Backend, path: str, body: bytes | None = None) -> Response:
    if body is None and request.method not in ("GET", "HEAD"):
        body = await read_body(request, BODY_LIMITS.get(route.template, DEFAULT_BODY_LIMIT))
        if body is None:
            return problem(413, "요청이 너무 큽니다.")
    headers = {k: v for k in REQUEST_HEADERS if (v := request.headers.get(k))}
    headers["x-studio-token"] = backend.token
    headers["host"] = backend.host
    query = request.url.query
    # One client per request: it is closed when the (possibly streamed) response ends.
    client = backend.client(timeout=TIMEOUT)
    upstream = client.build_request(request.method, backend.url + path + (f"?{query}" if query else ""),
                                    headers=headers, content=body)
    return await relay(client, upstream, route.response_filter)


async def post_file(backend: Backend, path: str, filename: str, data: bytes, media_type: str) -> Response:
    """Gateway-built multipart upload to the backend (validated, metadata-free bytes only)."""
    client = backend.client(timeout=TIMEOUT)
    upstream = client.build_request("POST", backend.url + path, files={"file": (filename, data, media_type)},
                                    headers={"x-studio-token": backend.token, "host": backend.host})
    return await relay(client, upstream, "project")


async def relay(client: httpx.AsyncClient, upstream: httpx.Request, response_filter: str | None) -> Response:
    try:
        response = await client.send(upstream, stream=True)
    except httpx.HTTPError:
        await client.aclose()
        return problem(502, "작업 서버에 연결하지 못했습니다. 잠시 뒤 다시 시도하세요.")
    out_headers = {k: v for k in RESPONSE_HEADERS if (v := response.headers.get(k))}
    out_headers.update({k: v for k, v in response.headers.items() if k.lower().startswith("x-render-")})
    mesh_type = MESH_TYPES.get(Path(upstream.url.path).suffix.lower())
    if mesh_type and response.status_code < 400:
        out_headers["content-type"] = mesh_type
    if response.status_code >= 400:
        raw = await response.aread()
        await response.aclose()
        await client.aclose()
        message = "요청을 처리하지 못했습니다."
        try:
            detail = json.loads(raw).get("detail")
            if isinstance(detail, str) and not redact.contains_path(detail):
                message = detail
            elif isinstance(detail, list):
                message = "입력 내용을 확인하세요."
        except (ValueError, AttributeError):
            pass
        reply = problem(response.status_code, message)
        if "x-live-state" in out_headers:
            reply.headers["x-live-state"] = out_headers["x-live-state"]
        return reply
    if response_filter:
        raw = await response.aread()
        await response.aclose()
        await client.aclose()
        try:
            data = redact.value(json.loads(raw))
        except ValueError:
            return problem(502, "작업 서버 응답을 읽지 못했습니다.")
        return JSONResponse(data, status_code=response.status_code, headers={"Cache-Control": "no-store"})

    async def stream():
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    if "text/event-stream" in out_headers.get("content-type", ""):
        out_headers["X-Accel-Buffering"] = "no"
        out_headers["Cache-Control"] = "no-store"
    return StreamingResponse(stream(), status_code=response.status_code, headers=out_headers)


async def fetch_json(backend: Backend, path: str) -> dict | list:
    """Gateway-internal GET to the backend (for summary endpoints)."""
    async with backend.client(timeout=httpx.Timeout(30)) as client:
        r = await client.get(backend.url + path, headers={"x-studio-token": backend.token, "host": backend.host})
    r.raise_for_status()
    return r.json()


async def post_json(backend: Backend, path: str, body: dict | None = None) -> tuple[int, dict]:
    """Gateway-internal POST to the backend; returns (status, JSON body or {})."""
    async with backend.client(timeout=httpx.Timeout(120)) as client:
        r = await client.post(backend.url + path, json=body or {},
                              headers={"x-studio-token": backend.token, "host": backend.host})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


async def post_raw(backend: Backend, path: str, body: bytes | None) -> tuple[int, dict]:
    """Gateway-internal POST of a stored JSON body (a queued GPU request started later)."""
    async with backend.client(timeout=httpx.Timeout(120)) as client:
        r = await client.post(backend.url + path, content=body or b"{}",
                              headers={"x-studio-token": backend.token, "host": backend.host, "content-type": "application/json"})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}
