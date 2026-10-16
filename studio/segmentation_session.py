"""API-side owner of persistent interactive segmentation processes (one per GPU).

* Started lazily on the first click, reused for every following click.
* Holds the per-GPU lock while alive; any queued GPU job asks it to close first
  (``release(device)``), so live selection and long jobs never share VRAM.
* Closed after ``session_idle_seconds`` without use to give memory back.
* Requests are strictly sequential; the latest-wins policy lives in
  ``studio.live_prompt`` (older revisions are never sent once a newer one exists).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from studio.doctor import ROOT
from studio import gpu_lock

_sessions: dict = {}
_guard = threading.Lock()


class SessionError(RuntimeError):
    pass


def failure_description(message, log=None, since=0):
    """Translate a real CUDA OOM without misclassifying an older session's log."""
    detail = str(message)
    if log is not None:
        try:
            with Path(log).open("rb") as stream:
                stream.seek(max(since, Path(log).stat().st_size - 16000))
                detail += stream.read().decode("utf-8", errors="replace")
        except OSError:
            pass
    if "out of memory" in detail.lower() or "cuda_error_out_of_memory" in detail.lower():
        return "객체 선택에 필요한 GPU 메모리가 부족합니다. 다른 GPU 작업을 종료하거나 메모리가 충분한 GPU를 선택한 뒤 다시 시도하세요. 클릭과 이전 마스크는 보존했습니다."
    return str(message)


class _Session:
    def __init__(self, device: str, log: Path, idle: int):
        from studio.engines import provider

        self.device, self.idle = device, idle
        from studio import live_render

        live_render.release(device)  # object selection takes the GPU from the live viewer
        self.lock = gpu_lock.try_acquire(device)
        if self.lock is None:
            raise SessionError("다른 GPU 작업이 실행 중입니다. 작업이 끝난 뒤 다시 클릭하세요.")
        env = os.environ.copy()
        env.update(CUDA_VISIBLE_DEVICES=str(device), OMP_NUM_THREADS="4", PYTHONUNBUFFERED="1")
        env.setdefault("STUDIO_OWNER_PID", str(os.getpid()))
        env.setdefault("STUDIO_OWNER_START", Path(f"/proc/{os.getpid()}/stat").read_text().split()[21])
        log.parent.mkdir(parents=True, exist_ok=True)
        self.log_path = log
        self.log_start = log.stat().st_size if log.exists() else 0
        self.log = log.open("a")
        self.proc = subprocess.Popen(
            [sys.executable, *provider("segmentation").session_command()],
            cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.log, text=True, bufsize=1, start_new_session=True,
        )
        self.io = threading.Lock()
        self.last_used = time.monotonic()
        self.counter = 0
        ready = self._read(timeout=600)
        if not ready.get("ready"):
            self.close()
            raise SessionError(ready.get("error") or "객체 선택 엔진을 시작하지 못했습니다. 로그를 확인하세요.")
        self.info = ready

    def _read(self, timeout):
        result = {}

        def reader():
            line = self.proc.stdout.readline()
            if line:
                try:
                    result.update(json.loads(line))
                except ValueError:
                    result["error"] = "엔진 응답을 해석하지 못했습니다."

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive() or not result:
            code = self.proc.poll()
            self.close()
            fallback = "객체 선택 엔진이 응답하지 않습니다." if code is None else "객체 선택 엔진이 종료되었습니다. 로그를 확인하세요."
            raise SessionError(failure_description(fallback, self.log_path, self.log_start))
        return result

    def predict(self, image, points, labels, output, timeout=120):
        with self.io:
            if self.proc.poll() is not None:
                raise SessionError("객체 선택 엔진이 종료되었습니다.")
            self.counter += 1
            request = {"op": "predict", "id": self.counter, "image": str(image),
                       "points": points, "labels": labels, "output": str(output)}
            self.proc.stdin.write(json.dumps(request) + "\n")
            self.proc.stdin.flush()
            reply = self._read(timeout)
            self.last_used = time.monotonic()
            return reply

    def alive(self):
        return self.proc.poll() is None

    def close(self):
        try:
            if self.proc.poll() is None:
                try:
                    self.proc.stdin.write('{"op":"close"}\n')
                    self.proc.stdin.flush()
                    self.proc.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired, ValueError):
                    self.proc.kill()
                    self.proc.wait()
        finally:
            if self.lock:
                self.lock.close()
                self.lock = None
            try:
                self.log.close()
            except OSError:
                pass


_starting: dict = {}
_cancelled: set = set()


def get(device, log: Path):
    """Return the live session for a GPU, starting it (outside the registry lock) if needed."""
    from studio.engines import config

    device = str(device)
    idle = int(config()["segmentation"]["options"].get("session_idle_seconds", 600))
    while True:
        with _guard:
            session = _sessions.get(device)
            if session and session.alive():
                return session
            if session:
                session.close()  # release the dead process's flock BEFORE starting its replacement
            _sessions.pop(device, None)
            waiter = _starting.get(device)
            if waiter is None:
                waiter = _starting[device] = threading.Event()
                _cancelled.discard(device)
                owner = True
            else:
                owner = False
        if not owner:
            waiter.wait(900)
            continue
        try:
            session = _Session(device, log, idle)
        finally:
            with _guard:
                _starting.pop(device, None)
            waiter.set()
        with _guard:
            if device in _cancelled:
                _cancelled.discard(device)
                session.close()
                raise SessionError("GPU 작업이 시작되어 객체 선택을 잠시 멈췄습니다. 작업이 끝난 뒤 다시 클릭하세요.")
            _sessions[device] = session
            _ensure_reaper()
            return session


def release(device=None):
    """Close sessions (all, or for one GPU) so a GPU job can take the device."""
    with _guard:
        keys = list(_sessions) if device is None else [k for k in _sessions if k == str(device)]
        closing = [_sessions.pop(k) for k in keys]
        _cancelled.update(_starting if device is None else [d for d in _starting if d == str(device)])
    for session in closing:
        session.close()


def status():
    sessions = dict(_sessions)  # lock-free snapshot for diagnostics
    out = {k: {"alive": s.alive(), "idle_seconds": round(time.monotonic() - s.last_used), **s.info}
           for k, s in sessions.items()}
    for device in list(_starting):
        out.setdefault(device, {"alive": False, "starting": True})
    return out


_reaper = None


def _ensure_reaper():
    global _reaper
    if _reaper and _reaper.is_alive():
        return

    def loop():
        while True:
            time.sleep(15)
            with _guard:
                stale = [k for k, s in _sessions.items() if not s.alive() or time.monotonic() - s.last_used > s.idle]
                closing = [_sessions.pop(k) for k in stale]
                empty = not _sessions
            for session in closing:
                session.close()
            if empty:
                return

    _reaper = threading.Thread(target=loop, daemon=True)
    _reaper.start()
