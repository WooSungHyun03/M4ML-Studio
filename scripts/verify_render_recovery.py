#!/usr/bin/env python3
"""Actual CUDA renderer startup-failure/retry smoke; trained source is read-only.

Usage: .runtime/bin/python scripts/verify_render_recovery.py PROJECT_DIR OUTPUT_DIR
The injected connection failure occurs AFTER the real Gaussian model loads on CUDA.
This does not train a new model or substitute a renderer.
"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import gpu_lock, live_render
from studio.gaussian_protocol import gl_view_from_colmap
from studio.providers.render_gaussian_remote import GaussianRemoteRenderingProvider


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    root, out = map(lambda s: Path(s).resolve(), sys.argv[1:])
    out.mkdir(parents=True, exist_ok=True)
    manifest = root / "manifest.json"
    project = json.loads(manifest.read_text())
    provider = GaussianRemoteRenderingProvider()
    model = provider.locate_model(root, project)
    watched = [manifest, Path(model["ply"])]
    before = [digest(p) for p in watched]
    device = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"], text=True
    ).splitlines()[0].strip()
    report = {"device": device, "iteration": model["iteration"], "gaussians": model["gaussians"], "checks": []}
    children = []
    popen = subprocess.Popen

    def spawn(*args, **kwargs):
        proc = popen(*args, **kwargs)
        children.append(proc)
        return proc

    class BrokenConnection(GaussianRemoteRenderingProvider):
        def connect(self, port):
            raise ConnectionRefusedError("deliberately injected after actual CUDA model load")

    session = None
    try:
        with patch("studio.engines.provider", return_value=BrokenConnection()), \
                patch("studio.live_render.subprocess.Popen", side_effect=spawn):
            try:
                live_render._Session(device, project["id"], model, out / "failed-start.log", 300)
            except live_render.LiveRenderError as exc:
                report["failure"] = str(exc)
            else:
                raise AssertionError("injected connection error was not reported")
        assert len(children) == 1 and children[0].poll() is not None
        report["checks"].append({"name": "failed CUDA child reaped", "pid": children[0].pid, "pass": True})
        lock = gpu_lock.try_acquire(device)
        assert lock is not None, "failed startup retained GPU lock"
        lock.close()
        report["checks"].append({"name": "physical GPU reservation released", "pass": True})
        session = live_render._Session(device, project["id"], model, out / "retry.log", 300)
        report["retry"] = session.status()
        c = model["cameras"][0]
        w2c = np.eye(4)
        w2c[:3, :3] = np.asarray(c["rotation"]).T
        w2c[:3, 3] = -w2c[:3, :3] @ np.asarray(c["position"])
        camera = {"view": gl_view_from_colmap(w2c).T.reshape(-1).tolist(), "width": 640, "height": 480,
                  "fovy": float(2 * np.arctan(c["height"] / (2 * c["fy"]))) }
        for mode in session.modes:
            frame, stats = session.frame({**camera, "mode": mode["key"]}, "png")
            (out / (mode["key"] + ".png")).write_bytes(frame)
            report["checks"].append({"name": mode["key"], "bytes": len(frame), "stats": stats, "pass": True})
        pid = session.proc.pid
        session.close()
        session.close()  # close is idempotent, including pipe cleanup
        assert session.proc.poll() is not None
        assert session.proc.stdin.closed and session.proc.stdout.closed and session.log.closed
        lock = gpu_lock.try_acquire(device)
        assert lock is not None
        lock.close()
        report["checks"].append({"name": "successful CUDA child reaped and lock released", "pid": pid, "pass": True})
        assert [digest(p) for p in watched] == before
        report["source_unchanged"] = dict(zip(["manifest", "gaussian_ply"], before))
        report["pass"] = True
    finally:
        if session:
            session.close()
        for proc in children:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
        (out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
