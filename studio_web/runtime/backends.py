"""Session backends: one existing `studio.api` process per active session.

Each backend gets its own STUDIO_DATA (never the default path), its own secret token, a
minimal environment and a configuration folder that only names the operator's SAM weights.
Backends start in their own process session and are *not* tied to the gateway's lifetime:
stopping a backend cancels its jobs (studio.worker watches its owner), so a gateway restart
must not stop them. After a restart the gateway re-adopts them from the registry.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from studio_web.config import ROOT, Config
from studio_web.persistence.db import Database
from studio_web.runtime.sandbox import SESSION_MOUNT, SandboxSpec, bwrap_argv, environment

log = logging.getLogger("studio_web.backends")

# Application files a session backend (and its workers) may read inside a sandbox. Nothing
# else of the installation folder (datasets, evidence, other sessions) is visible there.
APP_PATHS = ("studio", "arguments", "scene", "gaussian_renderer", "utils", "lpipsPyTorch", "submodules",
             "vendor", "runtime", "licenses", "docs", "frontend/dist", "train.py", "render.py", "view.py",
             "LICENSE.md", "NOTICE", "THIRD_PARTY_NOTICES.md", "SOURCES.json", "release-manifest.json")
SOCKET = "backend.sock"
MAX_SOCKET_PATH = 100  # sun_path is 108 bytes


@dataclass(frozen=True)
class Backend:
    session_id: str
    port: int  # 0 when the backend listens on its UNIX socket
    token: str
    pid: int
    pid_start: str
    socket: str | None = None

    @property
    def url(self) -> str:
        return "http://backend" if self.socket else f"http://127.0.0.1:{self.port}"

    @property
    def host(self) -> str:
        return "127.0.0.1" if self.socket else f"127.0.0.1:{self.port}"

    def client(self, **kw) -> httpx.AsyncClient:
        transport = httpx.AsyncHTTPTransport(uds=self.socket) if self.socket else None
        return httpx.AsyncClient(transport=transport, **kw)

    def sync_client(self, **kw) -> httpx.Client:
        transport = httpx.HTTPTransport(uds=self.socket) if self.socket else None
        return httpx.Client(transport=transport, **kw)


def _cmdline(pid: int) -> bytes:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return b""


def _signal(pid: int, sig: int):
    try:
        os.killpg(-pid, sig) if pid < 0 else os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _descendants(root: int) -> list[tuple[int, str]]:
    """All live descendants of `root` as (pid, start time) — start time guards against reuse."""
    children: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                ppid = int((entry / "stat").read_text().rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                continue
            children.setdefault(ppid, []).append(int(entry.name))
    out, stack = [], list(children.get(root, []))
    while stack:
        pid = stack.pop()
        start = _start_time(pid)
        if start:
            out.append((pid, start))
        stack += children.get(pid, [])
    return out


def _start_time(pid: int) -> str | None:
    """Start time of a live process (None if gone or a zombie waiting to be reaped)."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except (OSError, IndexError):
        return None
    return None if fields[0] in ("Z", "X") else fields[19]


class BackendError(RuntimeError):
    pass


class Backends:
    def __init__(self, config: Config, db: Database):
        self.config, self.db = config, db
        self._locks: dict[str, asyncio.Lock] = {}

    def socket_path_fits(self) -> bool:
        """Session ids are 32 hex characters; a longer home cannot hold any backend socket."""
        return len(str(self.session_dir("0" * 32) / SOCKET)) <= MAX_SOCKET_PATH

    def session_dir(self, session_id: str) -> Path:
        if not session_id.isalnum():
            raise ValueError("session id")
        return self.config.sessions_dir / session_id

    def _environment(self, session_id: str, token: str, sandboxed: bool = False) -> dict[str, str]:
        base = self.session_dir(session_id)
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(base, 0o700)  # parents=True below would otherwise leave it at the umask default
        for sub in ("data", "home", "config/m4ml-studio"):
            (base / sub).mkdir(parents=True, exist_ok=True, mode=0o700)
        self.config.gpu_lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Web sessions hand the GPU back quickly when idle (desktop defaults: 600 s / 300 s).
        settings = {"schema_version": 2, "engines": {"segmentation": {"options": {"session_idle_seconds": 120}},
                                                     "rendering": {"options": {"idle_seconds": 60}}}}
        if self.config.checkpoint:
            settings["engines"]["segmentation"]["options"]["checkpoint"] = str(self.config.checkpoint)
        (base / "config/m4ml-studio/settings.json").write_text(json.dumps(settings))
        inner = Path(SESSION_MOUNT) if sandboxed else base  # the backend's view of its folder
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin") if not sandboxed else "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "HOME": str(inner / "home"),
            "XDG_CONFIG_HOME": str(inner / "config"),
            "XDG_CACHE_HOME": str(inner / "home/.cache"),
            "XDG_RUNTIME_DIR": str(inner / "home"),
            "STUDIO_DATA": str(inner / "data"),
            "STUDIO_TOKEN": token,
            "STUDIO_MODE": "web",
            # one lock for every session (and the desktop, when it is given the same folder)
            "STUDIO_GPU_LOCK_DIR": str(self.config.gpu_lock_dir),
            # The shared runtime's editable `sam3` install points into a desktop app folder
            # under the user's home, which a sandbox cannot see; use this tree's vendor copy.
            "PYTHONPATH": str(ROOT / "vendor/sam3"),
            # Workers print Korean messages; inside a sandbox the locale may fall back to ASCII.
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        for key in ("CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES"):
            if key in os.environ:
                env[key] = os.environ[key]
        return env

    def registered(self, session_id: str) -> Backend | None:
        with self.db.connect() as db:
            row = db.execute("SELECT * FROM backends WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            return None
        backend = Backend(row["session_id"], row["port"], row["token"], row["pid"], row["pid_start"], row["socket"])
        if _start_time(backend.pid) != backend.pid_start:  # gone, or the pid was reused
            with self.db.connect() as db:
                db.execute("DELETE FROM backends WHERE session_id=?", (session_id,))
            return None
        return backend

    def count(self) -> int:
        with self.db.connect() as db:
            rows = db.execute("SELECT session_id FROM backends").fetchall()
        return sum(1 for r in rows if self.registered(r["session_id"]))

    async def ensure(self, session_id: str) -> Backend:
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            backend = self.registered(session_id)
            if backend and await self._ready(backend, attempts=1):
                return backend
            if backend:
                self._terminate(backend)
            if self.count() >= self.config.max_active_sessions:
                raise BackendError("busy")
            return await asyncio.get_running_loop().run_in_executor(None, self._spawn, session_id)

    def command(self, session_id: str, token: str, program: list[str] | None = None) -> tuple[list[str], dict[str, str], str]:
        """argv, environment and host-side socket path for a session backend.

        The backend listens on a UNIX socket in its own folder (0700): no TCP port that
        other local accounts could reach. With sandbox=bwrap it also sees nothing but its
        folder, the application files, the shared GPU lock folder and the GPU.
        """
        base = self.session_dir(session_id)
        socket_path = base / SOCKET
        if len(str(socket_path)) > MAX_SOCKET_PATH:
            raise BackendError("세션 폴더 경로가 너무 깁니다.")
        sandboxed = self.config.sandbox == "bwrap"
        env = self._environment(session_id, token, sandboxed)
        listen = f"{SESSION_MOUNT}/{SOCKET}" if sandboxed else str(socket_path)
        argv = program or [str(self.config.python), "-m", "uvicorn", "studio.api:app", "--uds", listen,
                           "--log-level", "warning", "--no-access-log"]
        if sandboxed:
            read_only = [ROOT / p for p in APP_PATHS if (ROOT / p).exists()]
            read_only.append(Path(self.config.python).resolve().parents[1])  # the runtime prefix
            if self.config.checkpoint:
                read_only.append(self.config.checkpoint.parent)
            spec = SandboxSpec(base, tuple(dict.fromkeys(read_only)), read_write=(self.config.gpu_lock_dir,),
                               network=False, gpu=True, env=env, chdir=ROOT, die_with_parent=False)
            argv = bwrap_argv(spec, argv, self.config.bwrap)
            env = environment(spec)  # passed to bwrap's process, inherited by the sandbox
        return argv, env, str(socket_path)

    def _spawn(self, session_id: str) -> Backend:
        token = secrets.token_urlsafe(32)
        log_file = (self.session_dir(session_id) / "home").joinpath("backend.log")
        argv, env, socket_path = self.command(session_id, token)
        if os.path.exists(socket_path):
            os.unlink(socket_path)
        with open(log_file, "ab") as out:
            proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
        # Reap the child whenever it exits, so a long-running gateway collects no zombies.
        threading.Thread(target=proc.wait, daemon=True, name=f"reap-{proc.pid}").start()
        backend = Backend(session_id, 0, token, proc.pid, _start_time(proc.pid) or "", socket_path)
        deadline = time.monotonic() + self.config.backend_start_timeout
        with backend.sync_client(timeout=2) as client:
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    # the operator reads the cause in the service journal (the log file itself
                    # is in the session folder, readable only by the service account)
                    log.warning("session %s backend exited (%s): %s", session_id[:8], proc.returncode, _tail(log_file))
                    raise BackendError("세션 백엔드를 시작하지 못했습니다.")
                try:
                    r = client.get(backend.url + "/api/about", headers={"x-studio-token": token, "host": backend.host})
                    if r.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            else:
                self._terminate(backend)
                raise BackendError("세션 백엔드가 제때 준비되지 않았습니다.")
        with self.db.connect() as db:
            db.execute("INSERT OR REPLACE INTO backends(session_id, port, token, pid, pid_start, started, socket) VALUES (?,?,?,?,?,?,?)",
                       (session_id, 0, token, proc.pid, backend.pid_start, time.time(), socket_path))
        self.db.audit(session_id, "backend started")
        return backend

    async def _ready(self, backend: Backend, attempts: int = 1) -> bool:
        async with backend.client(timeout=2) as client:
            for _ in range(attempts):
                try:
                    r = await client.get(backend.url + "/api/about", headers={"x-studio-token": backend.token, "host": backend.host})
                    if r.status_code == 200:
                        return True
                except httpx.HTTPError:
                    pass
        return False

    def _terminate(self, backend: Backend, timeout: float = 20):
        """Stop the backend and everything below it.

        The tree matters: inside a sandbox uvicorn runs in its own session under bwrap, and
        job workers always start new sessions, so killing one process group is not enough.
        uvicorn gets SIGTERM first (its lifespan cancels jobs and frees the GPU), then any
        survivor of the recorded tree is killed.
        """
        if _start_time(backend.pid) == backend.pid_start:
            tree = [(backend.pid, backend.pid_start)] + _descendants(backend.pid)
            for pid, _ in tree:
                if b"uvicorn" in _cmdline(pid):
                    _signal(pid, signal.SIGTERM)
            _signal(-backend.pid, signal.SIGTERM)
            end = time.monotonic() + timeout
            while time.monotonic() < end and any(_start_time(p) == s for p, s in tree):
                time.sleep(0.1)
            for pid, start in tree:
                if _start_time(pid) == start:
                    _signal(pid, signal.SIGKILL)
        with self.db.connect() as db:
            db.execute("DELETE FROM backends WHERE session_id=?", (backend.session_id,))

    def stop(self, session_id: str):
        backend = self.registered(session_id)
        if backend:
            self._terminate(backend)
            self.db.audit(session_id, "backend stopped")


def _tail(path: Path, lines: int = 5, limit: int = 600) -> str:
    """Last lines of a backend log for the journal, with session paths cut short."""
    try:
        text = path.read_bytes()[-8192:].decode("utf-8", "replace")
    except OSError:
        return "(no log)"
    out = " | ".join(line.strip() for line in text.strip().splitlines()[-lines:])
    return out.replace(str(path.parent.parent), "<session>")[-limit:]
