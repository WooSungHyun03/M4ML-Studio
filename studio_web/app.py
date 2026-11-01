"""M4ML Studio Web gateway (FastAPI). Assembly only: policy, sessions, backends, proxy.

  STUDIO_WEB_HOME=/srv/m4ml-web .runtime/bin/python -m uvicorn studio_web.app:app --host 127.0.0.1 --port 8800

Listens on loopback only; Cloudflare Tunnel (Phase 5) is the only intended way in.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import signal
import time
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from studio_web import config as config_module
from studio_web.auth.sessions import CSRF_COOKIE, SESSION_COOKIE, Recovery, Session, Sessions, issuance_allowed
from studio_web.auth.slots import Slots
from studio_web.services import retention
from studio_web.persistence.db import Database
from studio_web.runtime.backends import BackendError, Backends, _descendants
from studio_web.runtime.gpu_leases import GpuLeases, gpu_device, gpu_processes, kind_of
from studio_web.security import redact
from studio_web.security.route_policy import Rejected, match, normalise
from studio_web.security import limits, turnstile
from studio_web.security.rate_limit import RateLimiter
from html import escape as html_escape
from studio_web.security import upload_validation as uploads
from studio_web.runtime import gpu_leases
from studio_web.streaming.proxy import (BODY_LIMITS, DEFAULT_BODY_LIMIT, fetch_json, forward, post_file, post_json,
                                        post_raw, problem, read_body)

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "font-src 'self'; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), usb=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
NO_SESSION = "작업 공간이 없거나 만료되었습니다. 페이지를 새로 고치세요."
CANCEL_WAIT_SECONDS = 120  # deleting a project first waits this long for its running job to stop
ORPHAN_GRACE_SECONDS = 30  # job processes left without a running stage are stopped after this long
# Long-lived processes a session backend legitimately keeps between jobs.
RESIDENT_MARKERS = (b"uvicorn", b"bwrap", b"studio.sam31_session", b"gaussian_render_server", b"SIBR",
                    b"multiprocessing.resource_tracker", b"nvidia-smi")


def _kill(pid: int, sig: int):
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


log = logging.getLogger("studio_web.gateway")


def create_app(cfg: config_module.Config | None = None) -> FastAPI:
    cfg = cfg or config_module.load()
    cfg.sessions_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = Database(cfg.database)
    sessions = Sessions(db, cfg.session_days)
    backends = Backends(cfg, db)
    slots = Slots(db, cfg.max_active_sessions)
    recovery = Recovery(db)
    upload_locks: dict[str, asyncio.Lock] = {}
    leases = GpuLeases(db, cfg.gpu_lock_dir, gpu_device(), cfg.home / "maintenance")
    cancel_sent: set[str] = set()
    orphan_seen: dict[str, float] = {}

    @asynccontextmanager
    async def lifespan(app):
        tasks = [asyncio.create_task(reclaim_idle_slots()), asyncio.create_task(expire_sessions()),
                 asyncio.create_task(gpu_monitor_loop())]
        yield
        for task in tasks:
            task.cancel()

    async def expire_sessions():
        """At start and every 10 minutes: delete expired workspaces, finish interrupted deletions."""
        while True:
            await asyncio.get_running_loop().run_in_executor(None, retention.sweep, db, backends, slots)
            await asyncio.sleep(600)

    app = FastAPI(title="M4ML Studio Web", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.config, app.state.db, app.state.sessions, app.state.backends = cfg, db, sessions, backends
    app.state.slots, app.state.recovery, app.state.leases = slots, recovery, leases

    def external_gpu_busy() -> bool:
        """A CUDA process on the GPU that no web backend started (e.g. the desktop app)."""
        ours = set()
        with db.connect() as conn:
            for row in conn.execute("SELECT session_id FROM backends"):
                backend = backends.registered(row["session_id"])
                if backend:
                    ours.add(backend.pid)
                    ours.update(pid for pid, _ in _descendants(backend.pid))
        return any(pid not in ours for pid in gpu_processes())

    async def session_running(session_id: str) -> bool:
        backend = backends.registered(session_id)
        if not backend:
            return False
        try:
            projects = await fetch_json(backend, "/api/projects")
        except Exception:
            return True  # cannot tell: do not release
        return any(state == "running" for p in projects for state in (p.get("stages") or {}).values())

    def holder_gpu_pids(session_id: str) -> list[int]:
        """CUDA processes inside this session's backend tree (not the backend itself)."""
        backend = backends.registered(session_id)
        if not backend:
            return []
        tree = {pid for pid, _ in _descendants(backend.pid)}
        return [pid for pid in gpu_processes() if pid in tree]

    def stray_pids(session_id: str) -> list[int]:
        """Processes in the session's tree that are not its long-lived parts (backend, sandbox,
        object-selection session, live renderer). Only called when no stage is running."""
        backend = backends.registered(session_id)
        if not backend:
            return []
        out = []
        for pid, _ in _descendants(backend.pid):
            try:
                cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
                st = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
            except OSError:
                continue
            if st != "Z" and not any(marker in cmd for marker in RESIDENT_MARKERS):
                out.append(pid)
        return out

    async def gpu_monitor_once():
        owner = leases.owner()
        if owner:
            running = await session_running(owner["session_id"])
            pids = await asyncio.get_running_loop().run_in_executor(None, holder_gpu_pids, owner["session_id"])
            running = running or bool(pids)  # a GPU process of the holder still alive: keep the lease
            if owner["kind"] == "batch" and running and owner["started"] and \
                    time.time() - owner["started"] > gpu_leases.BATCH_MAX_SECONDS and owner["id"] not in cancel_sent:
                backend = backends.registered(owner["session_id"])
                if backend:
                    await post_json(backend, f"/api/projects/{owner['project_id']}/cancel")
                    cancel_sent.add(owner["id"])
                    db.audit(owner["session_id"], "batch GPU time limit reached; cancel requested")
            if leases.release_if_idle(running):
                db.audit(owner["session_id"], "GPU lease released")
            return
        loop = asyncio.get_running_loop()
        if not await loop.run_in_executor(None, leases.queue):
            return
        external = await loop.run_in_executor(None, external_gpu_busy)
        nxt = await loop.run_in_executor(None, lambda: leases.promote_next(external_busy=external))
        if nxt:
            backend = backends.registered(nxt["session_id"])
            if not backend:
                leases.finish(nxt["id"], "cancelled", "작업 공간이 닫혀 대기 작업을 취소했습니다.")
                return
            status, body = await post_raw(backend, nxt["route"], nxt["body"])
            if status >= 400:
                detail = body.get("detail") if isinstance(body.get("detail"), str) else "작업을 시작하지 못했습니다."
                leases.finish(nxt["id"], "failed", "" if redact.contains_path(detail) else detail)
            else:
                db.audit(nxt["session_id"], "queued GPU job started")

    async def reap_strays_once():
        """Job processes left in a session without a running stage (e.g. train.py or its
        children after the worker was killed) are stopped after a grace period."""
        with db.connect() as conn:
            sids = [r["session_id"] for r in conn.execute("SELECT session_id FROM backends")]
        loop = asyncio.get_running_loop()
        for sid in sids:
            strays = [] if await session_running(sid) else await loop.run_in_executor(None, stray_pids, sid)
            if not strays:
                orphan_seen.pop(sid, None)
                continue
            first = orphan_seen.setdefault(sid, time.time())
            if time.time() - first > ORPHAN_GRACE_SECONDS:
                for pid in strays:
                    _kill(pid, signal.SIGTERM)
                await asyncio.sleep(5)
                for pid in await loop.run_in_executor(None, stray_pids, sid):
                    _kill(pid, signal.SIGKILL)
                orphan_seen.pop(sid, None)
                db.audit(sid, f"left-over job processes stopped: {len(strays)}")

    async def gpu_monitor_loop():
        while True:
            for step in (gpu_monitor_once, reap_strays_once):
                try:
                    await step()
                except Exception:
                    pass  # never let the monitor die; the next round retries
            await asyncio.sleep(2)

    app.state.reap_strays_once = reap_strays_once

    app.state.gpu_monitor_once = gpu_monitor_once

    limiter = RateLimiter()
    app.state.limiter = limiter

    def rate_bucket(method: str, raw: str) -> str | None:
        if not raw.startswith("/api/"):
            return None
        if raw == "/api/web/session/recover":
            return "recover"
        if raw == "/api/web/session" and method == "POST":
            return "session"
        if method == "POST" and raw.endswith("/images"):
            return "upload"
        if raw.endswith("/live-render/frame"):
            return "frame"  # the viewer asks for 25+ frames a second while dragging
        return "api"

    def client_of(request: Request) -> str:
        """Client address for rate limits. CF-Connecting-IP only counts when the request came
        through the local tunnel and the operator said a tunnel is in front."""
        direct = request.client.host if request.client else "unknown"
        if cfg.trust_cloudflare and direct in ("127.0.0.1", "::1") and request.headers.get("cf-connecting-ip"):
            return request.headers["cf-connecting-ip"][:64]
        return direct

    async def has_running_work(session_id: str) -> bool:
        backend = backends.registered(session_id)
        if not backend:
            return False
        try:
            projects = await fetch_json(backend, "/api/projects")
        except Exception:
            return True  # unsure: keep it
        return any(state == "running" for p in projects for state in (p.get("stages") or {}).values())

    async def reclaim_idle_slots():
        """Every minute: an idle slot whose backend runs no job is freed for the next visitor.
        A backend with a running job keeps its slot (stopping it would cancel the job)."""
        while True:
            await asyncio.sleep(60)
            for sid in slots.idle():
                if not await has_running_work(sid):
                    await asyncio.get_running_loop().run_in_executor(None, backends.stop, sid)
                    slots.release(sid)
                    db.audit(sid, "idle slot reclaimed")

    def admission_body(admission):
        if admission.active:
            return {"slot": "active"}
        if admission.full:
            return {"slot": "full"}
        return {"slot": "queued", "position": admission.position}

    def host_of(request: Request) -> str:
        return request.headers.get("host", "").rsplit(":", 1)[0].lower().strip("[]")

    def origin_ok(request: Request) -> bool:
        origin = request.headers.get("origin")
        if not origin:
            return False
        host = request.headers.get("host", "")
        allowed = {f"https://{host}"}
        if host_of(request) in LOCAL_HOSTS:
            allowed.add(f"http://{host}")
        return origin in allowed

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        if host_of(request) not in cfg.hosts:
            response = problem(400, "잘못된 요청입니다.")
        else:
            raw = request.scope.get("raw_path", b"/").decode("latin-1").split("?", 1)[0]
            try:
                if raw != "/":
                    normalise(raw)
            except Rejected:
                response = problem(404, "찾을 수 없습니다.")
            else:
                bucket = rate_bucket(request.method, raw)
                if bucket == "session" and current(request):
                    # the page asks again on every load; only *new* workspaces use the tight
                    # budget, so a burst of failed attempts from the same address (or NAT)
                    # does not lock out people who already have a workspace
                    bucket = "api"
                if bucket and not limiter.allow(client_of(request), bucket):
                    response = problem(429, "요청이 너무 많습니다. 잠시 뒤 다시 시도하세요.")
                else:
                    response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            if key == "Content-Security-Policy" and cfg.turnstile_sitekey:
                value = value.replace("script-src 'self'", "script-src 'self' https://challenges.cloudflare.com") \
                    + "; frame-src https://challenges.cloudflare.com"
            response.headers.setdefault(key, value)
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    def current(request: Request) -> Session | None:
        return sessions.lookup(request.cookies.get(SESSION_COOKIE))

    def write_allowed(request: Request, session: Session) -> bool:
        return origin_ok(request) and Sessions.csrf_ok(session, request.headers.get("x-csrf-token"), request.cookies.get(CSRF_COOKIE))

    def set_cookies(response: Response, secret: str, session: Session):
        age = max(0, int(session.expires - __import__("time").time()))
        response.set_cookie(SESSION_COOKIE, secret, max_age=age, path="/", secure=True, httponly=True, samesite="lax")
        response.set_cookie(CSRF_COOKIE, session.csrf, max_age=age, path="/", secure=True, httponly=False, samesite="strict")

    async def backend_for(session: Session):
        admission = slots.admit(session.id)
        if not admission.active:
            reply = problem(503, "지금은 이용자가 많습니다. 잠시 뒤 다시 시도하세요.")
            reply.headers["x-queue-position"] = str(admission.position or "")
            return None, reply
        try:
            return await backends.ensure(session.id), None
        except BackendError as exc:
            log.warning("backend for session %s not started: %s", session.id[:8], exc)
            if str(exc) == "busy":
                return None, problem(503, "지금은 이용자가 많습니다. 잠시 뒤 다시 시도하세요.")
            return None, problem(503, "작업 공간을 준비하지 못했습니다. 잠시 뒤 다시 시도하세요.")

    # ---- health (no details: these may be reachable through the tunnel) ------------------
    @app.get("/api/web/live")
    async def live():
        return JSONResponse({"live": True}, headers={"Cache-Control": "no-store"})

    @app.get("/api/web/ready")
    async def ready():
        checks = {}
        try:
            db.version()
            checks["database"] = True
        except Exception:
            checks["database"] = False
        checks["ui"] = (cfg.frontend / "index.html").is_file()
        checks["storage"] = os.access(cfg.sessions_dir, os.W_OK)
        checks["socket_path"] = backends.socket_path_fits()  # a too-long home would fail every session
        ok = all(checks.values())
        gpu = "maintenance" if leases.maintenance_flag.exists() else "ok"
        return JSONResponse({"ready": ok, "gpu": gpu}, status_code=200 if ok else 503, headers={"Cache-Control": "no-store"})

    # ---- web session ------------------------------------------------------------------
    @app.post("/api/web/session")
    async def open_session(request: Request):
        if not origin_ok(request):
            return problem(403, "다른 사이트의 요청은 허용하지 않습니다.")
        session = current(request)
        if session:
            return JSONResponse({"expires": session.expires, **admission_body(slots.admit(session.id))})
        if cfg.turnstile_sitekey:
            try:
                token = (await request.json()).get("turnstile")
            except Exception:
                token = None
            verdict = await turnstile.verify(token if isinstance(token, str) else None,
                                             secret=cfg.turnstile_secret_file.read_text().strip(),
                                             url=cfg.turnstile_verify_url, remote_ip=client_of(request),
                                             expected_host=cfg.public_host)
            if not verdict.ok:
                db.audit(None, f"session refused: turnstile {verdict.reason}")
                log.warning("new session refused: turnstile %s", verdict.reason)
                reply = problem(403, "자동 등록 방지 확인이 필요합니다. 확인을 마친 뒤 다시 시도하세요.")
                reply.headers["x-turnstile"] = "required"
                return reply
        if not issuance_allowed(db, client_of(request)):
            return problem(429, "새 작업 공간을 너무 자주 만들었습니다. 잠시 뒤 다시 시도하세요.")
        session, secret = sessions.create()
        response = JSONResponse({"expires": session.expires, "new": True, **admission_body(slots.admit(session.id))})
        set_cookies(response, secret, session)
        return response

    @app.get("/api/web/session")
    async def session_status(request: Request):
        session = current(request)
        return JSONResponse({"active": bool(session), "expires": session.expires if session else None},
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/web/gpu")
    async def gpu_status(request: Request):
        session = current(request)
        if not session:
            return problem(401, NO_SESSION)
        return JSONResponse(leases.status_for(session.id), headers={"Cache-Control": "no-store"})

    @app.get("/api/web/queue")
    async def queue_status(request: Request):
        session = current(request)
        if not session:
            return problem(401, NO_SESSION)
        return JSONResponse(admission_body(slots.admit(session.id)), headers={"Cache-Control": "no-store"})

    @app.post("/api/web/session/recovery")
    async def recovery_link(request: Request):
        session = current(request)
        if not session:
            return problem(401, NO_SESSION)
        if not write_allowed(request, session):
            return problem(403, "보안 확인에 실패했습니다. 페이지를 새로 고치세요.")
        return JSONResponse({"token": recovery.issue(session), "expires": session.expires}, headers={"Cache-Control": "no-store"})

    @app.post("/api/web/session/recover")
    async def recover(request: Request):
        if not origin_ok(request):
            return problem(403, "다른 사이트의 요청은 허용하지 않습니다.")
        try:
            token = (await request.json()).get("token")
        except Exception:
            token = None
        redeemed = recovery.redeem(token if isinstance(token, str) else None)
        if not redeemed:
            return problem(404, "이어하기 링크가 올바르지 않거나 이미 사용되었습니다.")
        session, secret = redeemed
        response = JSONResponse({"expires": session.expires, **admission_body(slots.admit(session.id))})
        set_cookies(response, secret, session)
        return response

    # ---- gateway answers instead of the backend -------------------------------------------
    @app.get("/api/about")
    async def about(request: Request):
        if not current(request):
            return problem(401, NO_SESSION)
        from studio.config import VERSION

        manifest = config_module.ROOT / "release-manifest.json"
        release = json.loads(manifest.read_text()) if manifest.is_file() else {}
        return {"app": "M4ML Studio", "version": VERSION, "release": release.get("version"),
                "channel": release.get("channel"), "desktop": False, "web": True}

    async def summary(request: Request, path: str, shape):
        session = current(request)
        if not session:
            return problem(401, NO_SESSION)
        backend, error = await backend_for(session)
        if error:
            return error
        try:
            data = await fetch_json(backend, path)
        except Exception:
            return problem(502, "작업 서버 상태를 읽지 못했습니다.")
        return JSONResponse(redact.value(shape(data)), headers={"Cache-Control": "no-store"})

    def workspace_room(session) -> int:
        """Space this workspace may still use: its quota minus usage, never more than the
        server can give above its reserve (the host's own free space stays private)."""
        used = limits.directory_bytes(Path(backends.session_dir(session.id)))
        host = shutil.disk_usage(cfg.home).free - limits.MIN_FREE_BYTES
        return max(0, min(limits.SESSION_BYTES - used, host))

    @app.get("/api/health")
    async def health(request: Request):
        session = current(request)
        room = await asyncio.to_thread(workspace_room, session) if session else 0

        def shape(h):
            return {
                "app": h.get("app"), "version": h.get("version"),
                "gpus": [{k: g.get(k) for k in ("index", "name", "total_mb", "free_mb", "driver")} for g in h.get("gpus", [])],
                "gpu_error": "GPU 상태를 확인할 수 없습니다." if h.get("gpu_error") else None,
                "colmap": {k: (h.get("colmap") or {}).get(k) for k in ("available", "gpu")},
                "runtime_status": {k: (h.get("runtime_status") or {}).get(k) for k in ("available", "anchor_ok")},
                "checkpoint_exists": bool(h.get("checkpoint_exists")),
                "disk_free": room,  # this workspace's remaining quota, not the server disk
            }
        return await summary(request, "/api/health", shape)

    @app.get("/api/engines")
    async def engines(request: Request):
        return await summary(request, "/api/engines", lambda e: {"licenses": e.get("licenses", []), "engines": {}, "gpus": []})

    @app.get("/api/gpu-monitor")
    async def gpu_monitor(request: Request):
        return await summary(request, "/api/gpu-monitor", lambda m: {"gpus": m.get("gpus", []), "apps": [], "time": m.get("time")})

    @app.get("/api/projects/{project_id}/logs/{job_id}")
    async def job_log(request: Request, project_id: str, job_id: str):
        try:
            match("GET", f"/api/projects/{project_id}/training-metrics/{job_id}")  # same id grammar
        except Rejected:
            return problem(404, "찾을 수 없습니다.")
        return await summary(request, f"/api/projects/{project_id}/logs/{job_id}", lambda d: {"text": d.get("text", "")})

    @app.delete("/api/projects/{project_id}")
    async def delete_project(request: Request, project_id: str):
        """Cancel running work, wait for it to stop, then remove the project and its files."""
        try:
            match("PATCH", f"/api/projects/{project_id}")
        except Rejected:
            return problem(404, "찾을 수 없습니다.")
        session = current(request)
        if not session:
            return problem(401, NO_SESSION)
        if not write_allowed(request, session):
            return problem(403, "보안 확인에 실패했습니다. 페이지를 새로 고치세요.")
        backend, error = await backend_for(session)
        if error:
            return error
        base = f"/api/projects/{project_id}"
        try:
            doc = await fetch_json(backend, base)
        except Exception:
            return JSONResponse({"deleted": True})  # already gone: deleting twice is fine
        if any(state == "running" for state in doc.get("stages", {}).values()):
            await post_json(backend, base + "/cancel")
            for _ in range(int(CANCEL_WAIT_SECONDS * 2)):
                await asyncio.sleep(0.5)
                doc = await fetch_json(backend, base)
                if not any(state == "running" for state in doc.get("stages", {}).values()):
                    break
            else:
                return problem(409, "실행 중인 작업을 멈추지 못했습니다. 잠시 뒤 다시 시도하세요.")
        status, body = await post_json(backend, base + "/purge")
        if status >= 400:
            message = body.get("detail") if isinstance(body.get("detail"), str) and not redact.contains_path(body.get("detail")) else "삭제하지 못했습니다."
            return problem(status, message)
        db.audit(session.id, "project deleted")
        return JSONResponse({"deleted": True})

    @app.delete("/api/web/session")
    async def delete_workspace(request: Request):
        session = current(request)
        if not session:
            return problem(401, NO_SESSION)
        if not write_allowed(request, session):
            return problem(403, "보안 확인에 실패했습니다. 페이지를 새로 고치세요.")
        leases.drop_session(session.id)
        done = await asyncio.get_running_loop().run_in_executor(None, retention.delete_session, db, backends, slots, session.id)
        response = JSONResponse({"deleted": True, "complete": done})
        response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        response.delete_cookie(CSRF_COOKIE, path="/", secure=True, samesite="strict")
        return response

    @app.post("/api/projects/{project_id}/images")
    async def upload_image(request: Request, project_id: str):
        """Quarantine → limits → decode/strip metadata in a worker process → backend import."""
        try:
            match("PATCH", f"/api/projects/{project_id}")  # canonical project id
        except Rejected:
            return problem(404, "찾을 수 없습니다.")
        session = current(request)
        if not session:
            return problem(401, NO_SESSION)
        if not write_allowed(request, session):
            return problem(403, "보안 확인에 실패했습니다. 페이지를 새로 고치세요.")
        declared = request.headers.get("content-length", "")
        if not declared.isdigit():
            return problem(411, "파일 크기를 알 수 없습니다. 다시 시도하세요.")
        if int(declared) > uploads.MAX_BYTES + 64 * 1024:
            return problem(413, "사진 한 장은 20MB 이하만 올릴 수 있습니다.")
        try:
            form = await request.form(max_files=1, max_fields=0)
            item = form.get("file")
            data = await item.read(uploads.MAX_BYTES + 1) if hasattr(item, "read") else b""
            name = uploads.display_name(getattr(item, "filename", None))
        except Exception:
            return problem(400, "올린 파일을 읽지 못했습니다.")
        finally:
            if "form" in locals():
                await form.close()
        backend, error = await backend_for(session)
        if error:
            return error
        # One upload at a time per workspace: the quota check and the import cannot interleave.
        async with upload_locks.setdefault(session.id, asyncio.Lock()):
            try:
                project = await fetch_json(backend, f"/api/projects/{project_id}")
            except Exception:
                return problem(404, "프로젝트를 찾을 수 없습니다.")
            refusal = limits.admit_photo(cfg, backends.session_dir(session.id), project, len(data))
            if refusal:
                return problem(413, refusal)
            loop = asyncio.get_running_loop()
            try:
                clean, info = await loop.run_in_executor(None, uploads.validate_in_worker, data)
            except uploads.UploadRejected as exc:
                return problem(422, str(exc))
            # A retried upload of the same photo (e.g. after a dropped connection) is not stored twice.
            digest = hashlib.sha256(clean).hexdigest()
            if any(image.get("source_sha256") == digest for image in project.get("images", [])):
                return JSONResponse(redact.value(project), headers={"Cache-Control": "no-store", "X-Upload-Replay": "1"})
            media = "image/jpeg" if info["format"] == "JPEG" else "image/png"
            return await post_file(backend, f"/api/projects/{project_id}/images", name, clean, media)

    # ---- everything else under /api: policy, then the session's own backend ---------------
    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
    async def proxied(request: Request, rest: str):
        raw = request.scope.get("raw_path", b"").decode("latin-1").split("?", 1)[0]
        try:
            route, params = match(request.method, raw)
        except Rejected:
            return problem(404, "찾을 수 없습니다.")
        session = current(request)
        if not session:
            return problem(401, NO_SESSION)
        if request.method not in ("GET", "HEAD") and not write_allowed(request, session):
            return problem(403, "보안 확인에 실패했습니다. 페이지를 새로 고치세요.")
        if route.template in limits.OUTPUT_TEMPLATES and request.method == "POST":
            refusal = limits.admit_job(cfg, backends.session_dir(session.id))
            if refusal:
                return problem(413, refusal)
        backend, error = await backend_for(session)
        if error:
            return error
        if route.gpu:
            return await gpu_forward(request, route, backend, raw, session, params.get("project_id", ""))
        return await forward(request, route, backend, raw)

    async def gpu_forward(request, route, backend, raw, session, project_id):
        owner = leases.owner()
        if owner and owner["session_id"] == session.id and kind_of(route.template) == "interactive":
            return await forward(request, route, backend, raw)  # fast path: frames and clicks of the holder
        body = await read_body(request, BODY_LIMITS.get(route.template, DEFAULT_BODY_LIMIT))
        if body is None:
            return problem(413, "요청이 너무 큽니다.")
        # also when the holder turns a viewer lease into heavy work: the desktop may have started
        # on the GPU in the meantime (it does not take the shared lock)
        upgrade = bool(owner and owner["session_id"] == session.id and owner["kind"] == "interactive")
        external = await asyncio.get_running_loop().run_in_executor(None, external_gpu_busy) if (not owner or upgrade) else False
        grant = leases.request(session.id, project_id, route.template, raw, body, external_busy=external)
        if grant.status == "granted":
            response = await forward(request, route, backend, raw, body=body)
            if grant.new and response.status_code >= 400:
                leases.finish(grant.lease_id, "failed", "backend refused the request")
            return response
        if grant.status == "queued":
            return JSONResponse({"queued": True, "position": grant.position,
                                 "detail": f"GPU를 다른 작업이 쓰고 있습니다. 대기 {grant.position}번째이며 차례가 되면 자동으로 시작합니다."},
                                status_code=202, headers={"Cache-Control": "no-store"})
        messages = {
            "maintenance": "서버 점검 중이라 지금은 GPU 작업을 시작할 수 없습니다.",
            "external": "서버 GPU를 다른 프로그램이 쓰고 있습니다. 잠시 뒤 다시 시도하세요.",
            "budget": "오늘 사용할 수 있는 GPU 시간을 모두 썼습니다. 내일 다시 이용하세요.",
        }
        reply = problem(503, messages.get(grant.reason, "GPU를 다른 작업이 쓰고 있습니다. 앞선 작업이 끝나면 다시 시도하세요."))
        reply.headers["x-gpu-state"] = grant.reason or "busy"
        return reply

    # ---- the built UI ---------------------------------------------------------------------
    index = cfg.frontend / "index.html"

    @app.get("/recover", include_in_schema=False)
    @app.get("/", include_in_schema=False)
    async def home():
        if not index.is_file():
            return problem(503, "웹 화면이 설치되지 않았습니다.")
        meta = '<meta name="m4ml-platform" content="web" />'
        if cfg.turnstile_sitekey:
            meta += f'\n    <meta name="m4ml-turnstile" content="{html_escape(cfg.turnstile_sitekey)}" />'
        html = index.read_text().replace("<head>", "<head>\n    " + meta, 1)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    safe_static = re.compile(r"(?:assets|fonts)/[A-Za-z0-9._-]+|[A-Za-z0-9][A-Za-z0-9._-]*\.(?:png|ico|svg|woff2?|ttf)")

    @app.get("/{asset:path}", include_in_schema=False)
    async def static(asset: str):
        if not safe_static.fullmatch(asset):
            return problem(404, "찾을 수 없습니다.")
        file = (cfg.frontend / asset).resolve()
        if not file.is_relative_to(cfg.frontend) or not file.is_file():
            return problem(404, "찾을 수 없습니다.")
        cache = "public, max-age=31536000, immutable" if asset.startswith("assets/") else "public, max-age=3600"
        return FileResponse(file, headers={"Cache-Control": cache})

    @app.api_route("/{anything:path}", methods=["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"], include_in_schema=False)
    async def unknown(anything: str):
        return problem(404, "찾을 수 없습니다.")  # unknown paths look the same whatever the method

    return app


def __getattr__(name):  # `uvicorn studio_web.app:app` builds the app from the environment lazily
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
