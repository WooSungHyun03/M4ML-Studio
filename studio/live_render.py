"""API-side owner of the live Gaussian renderer process (the "실시간 렌더" viewport).

Policy (documented in docs/GAUSSIAN_VIEWER_INTEGRATION.md):

* At most one renderer per GPU; it holds the same per-GPU lock as training/mesh jobs and the
  object-selection session, so the viewer never shares VRAM with them.
* Starting a GPU job, or an object-selection click on that GPU, releases the renderer first
  (``release(device)``); the viewport then shows "연결 끊김" with a reconnect button.
* Opening another project/model on the same GPU replaces the renderer (old process stopped
  before the new one loads).
* Idle renderers close after ``rendering.options.idle_seconds`` to return VRAM.
* The renderer child exits when the backend dies (owner watchdog + stdin EOF), so a crash
  never leaves a process holding GPU memory.

Frames: the provider returns raw RGB from the renderer; this module encodes JPEG (moving
camera) or PNG (still camera, lossless) for the HTTP response.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from studio import gpu_lock
from studio.doctor import ROOT

_sessions: dict = {}
_guard = threading.Lock()


class LiveRenderError(RuntimeError):
    def __init__(self, message, state="failed"):
        super().__init__(message)
        self.state = state  # failed | out_of_memory | busy | disconnected


def _oom(text: str) -> bool:
    t = (text or "").lower()
    return "out of memory" in t or "cuda_error_out_of_memory" in t


class _Session:
    def __init__(self, device: str, project_id: str, model: dict, log: Path, idle: int):
        from studio.engines import provider

        self.device, self.project_id, self.model, self.idle = device, project_id, model, idle
        self.provider = provider("rendering")
        self.lock = gpu_lock.try_acquire(device)
        if self.lock is None:
            raise LiveRenderError("다른 GPU 작업이 실행 중입니다. 작업이 끝난 뒤 다시 시도하세요.", "busy")
        env = os.environ.copy()
        env.update(CUDA_VISIBLE_DEVICES=str(device), OMP_NUM_THREADS="4", PYTHONUNBUFFERED="1")
        env["STUDIO_OWNER_PID"] = str(os.getpid())
        env["STUDIO_OWNER_START"] = Path(f"/proc/{os.getpid()}/stat").read_text().split()[21]
        log.parent.mkdir(parents=True, exist_ok=True)
        self.log_path = log
        self.log = log.open("a")
        self.started = time.monotonic()
        self.proc = subprocess.Popen(
            self.provider.server_command(model), cwd=ROOT, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=self.log, text=True, bufsize=1, start_new_session=True,
        )
        self.io = threading.Lock()
        self.client = None
        self.external = None
        self.frames = 0
        self.last_used = time.monotonic()
        ready = self._read_ready(timeout=300)
        if not ready.get("ready"):
            err = ready.get("error") or "렌더러를 시작하지 못했습니다."
            self.close()
            if ready.get("oom") or _oom(err):
                raise LiveRenderError("실시간 렌더에 필요한 GPU 메모리가 부족합니다. 다른 GPU 프로그램을 종료한 뒤 다시 시도하세요.", "out_of_memory")
            raise LiveRenderError("렌더러를 시작하지 못했습니다: " + err)
        self.info = ready
        self.load_seconds = round(time.monotonic() - self.started, 2)
        self.client = self.provider.connect(ready["port"])
        self.modes = self.provider.modes(self.client.render_items)

    def _read_ready(self, timeout):
        box = {}

        def reader():
            for line in self.proc.stdout:
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if "ready" in msg:
                    box.update(msg)
                    return

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout)
        if not box:
            tail = ""
            try:
                tail = self.log_path.read_text(errors="replace")[-4000:]
            except OSError:
                pass
            return {"ready": False, "error": "렌더러가 응답하지 않습니다." if self.proc.poll() is None else "렌더러가 종료되었습니다.",
                    "oom": _oom(tail)}
        return box

    def alive(self):
        return self.proc.poll() is None

    def frame(self, camera: dict, encoding: str):
        from PIL import Image

        with self.io:
            if not self.alive() or self.client is None:
                raise LiveRenderError("렌더러 연결이 끊겼습니다.", "disconnected")
            mode = camera.get("mode", "rgb")
            index = next((m["index"] for m in self.modes if m["key"] == mode), 0)
            t0 = time.perf_counter()
            try:
                rgb, metrics = self.provider.render(self.client, {**camera, "mode_index": index})
            except (ConnectionError, OSError) as exc:
                self.client = None
                tail = self.log_path.read_text(errors="replace")[-4000:] if self.log_path.exists() else ""
                if _oom(tail):
                    raise LiveRenderError("실시간 렌더 중 GPU 메모리가 부족해졌습니다. 해상도를 낮추거나 다른 GPU 작업을 종료하세요.", "out_of_memory") from exc
                raise LiveRenderError("렌더러 연결이 끊겼습니다.", "disconnected") from exc
            t1 = time.perf_counter()
            w, h = int(camera["width"]), int(camera["height"])
            image = Image.frombuffer("RGB", (w, h), rgb, "raw", "RGB", 0, 1)
            out = io.BytesIO()
            if encoding == "png":
                image.save(out, "PNG", compress_level=1)
            else:
                image.save(out, "JPEG", quality=int(camera.get("quality", 88)))
            self.frames += 1
            self.last_used = time.monotonic()
            return out.getvalue(), {
                "render_ms": metrics.get("render ms"), "roundtrip_ms": round((t1 - t0) * 1000, 2),
                "encode_ms": round((time.perf_counter() - t1) * 1000, 2), "gaussians": metrics.get("#"),
            }

    def open_external(self):
        if self.external and self.external.poll() is None:
            return
        argv = self.provider.external_viewer_command(self.info["port"], self.model)
        if not argv:
            raise LiveRenderError("외부 뷰어를 사용할 수 없습니다. 설정 › 고급 정보에서 상태를 확인하세요.")
        self.external = subprocess.Popen(argv, cwd=Path(argv[0]).parent, stdin=subprocess.DEVNULL,
                                         stdout=self.log, stderr=self.log, start_new_session=True)

    def status(self):
        return {
            "state": "rendering" if self.alive() and self.client else "disconnected",
            "device": self.device, "project_id": self.project_id, "iteration": self.model["iteration"],
            "gaussians": self.info.get("gaussians"), "load_seconds": self.load_seconds,
            "renderer_vram_mb": self.info.get("vram_mb"), "frames": self.frames,
            "idle_seconds": round(time.monotonic() - self.last_used), "modes": self.modes,
            "pid": self.proc.pid, "external_viewer": bool(self.external and self.external.poll() is None),
        }

    def close(self):
        if self.external and self.external.poll() is None:
            self.external.terminate()
            try:
                self.external.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.external.kill()
        if self.client is not None:
            self.client.close()
            self.client = None
        try:
            if self.proc.poll() is None:
                try:
                    self.proc.stdin.close()  # renderer exits on stdin EOF
                    self.proc.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                        self.proc.wait()
        finally:
            self.log.close()
            if self.lock:
                self.lock.close()
                self.lock = None


def start(device: str, project_id: str, model: dict, log: Path) -> dict:
    from studio.engines import config

    idle = int(config()["rendering"]["options"].get("idle_seconds", 300))
    # Interactive object selection on this GPU must give the device up first. Done before
    # taking our guard: segmentation_session also calls release() here (lock-order safety).
    from studio import segmentation_session

    if not (_sessions.get(device) and _sessions[device].project_id == project_id):
        segmentation_session.release(device)
    with _guard:
        current = _sessions.get(device)
        if current and current.alive() and current.project_id == project_id \
                and current.model["ply"] == model["ply"] and current.client is not None:
            current.last_used = time.monotonic()
            return current.status()
        if current:
            current.close()
            _sessions.pop(device, None)
        session = _Session(device, project_id, model, log, idle)
        _sessions[device] = session
        _ensure_reaper()
        return session.status()


def session_for(project_id: str):
    with _guard:
        return next((s for s in _sessions.values() if s.project_id == project_id), None)


def frame(project_id: str, camera: dict, encoding: str):
    session = session_for(project_id)
    if session is None:
        raise LiveRenderError("실시간 렌더가 시작되지 않았습니다.", "disconnected")
    return session.frame(camera, encoding)


def release(device=None, project_id=None):
    with _guard:
        keys = [k for k, s in _sessions.items()
                if (device is None or k == device) and (project_id is None or s.project_id == project_id)]
        for k in keys:
            _sessions.pop(k).close()
        return len(keys)


def status():
    with _guard:
        return {k: s.status() for k, s in _sessions.items()}


_reaper = None


def _ensure_reaper():
    global _reaper
    if _reaper and _reaper.is_alive():
        return

    def loop():
        while True:
            time.sleep(10)
            with _guard:
                stale = [k for k, s in _sessions.items() if not s.alive() or time.monotonic() - s.last_used > s.idle]
                for k in stale:
                    _sessions.pop(k).close()

    _reaper = threading.Thread(target=loop, daemon=True)
    _reaper.start()


if __name__ == "__main__":
    # `python -m studio.live_render --check-external`: report the external viewer runtime.
    from studio.providers.render_gaussian_remote import sibr_binary, missing_libraries

    if "--check-external" in sys.argv:
        b = sibr_binary()
        print(json.dumps({"binary": str(b) if b else None, "missing_libraries": missing_libraries(b) if b else None}))
