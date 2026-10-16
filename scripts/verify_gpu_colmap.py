#!/usr/bin/env python3
"""Real GPU camera-reconstruction check through the production provider.

  .runtime/bin/python scripts/verify_gpu_colmap.py IMAGES OUTPUT [--cpu] [--gpu 0]

Runs feature extraction → matching → mapper → undistortion with the configured
(bundled) COLMAP, samples nvidia-smi during GPU steps, validates the undistorted scene
with the training loader's readers and writes OUTPUT/verification.json.
Nothing is mocked; failures exit non-zero.
"""

import argparse, json, os, subprocess, sys, threading, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.engines import provider  # noqa: E402
from studio.providers.base import JobContext  # noqa: E402
from studio.doctor import ROOT  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--cpu", action="store_true", help="explicit CPU run (comparison)")
    ap.add_argument("--gpu", default="0")
    ap.add_argument("--matching", default="exhaustive")
    a = ap.parse_args()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.update(CUDA_VISIBLE_DEVICES=a.gpu, OMP_NUM_THREADS="4")
    messages = []
    ctx = JobContext(root=out, output=out, log=out / "colmap.log", env=env, cancel=threading.Event(),
                     progress=lambda m, c=None, t=None: messages.append([time.time(), m, c, t]), cwd=ROOT)
    camera = provider("camera")
    started = time.time()
    request = {"matching": a.matching}
    if a.cpu:
        request.update(cpu_fallback=True, cpu_fallback_confirmed=True)
    report = camera.reconstruct(ctx, a.images.resolve(), out / "colmap", request)
    elapsed = time.time() - started
    step_times = []
    for line in (out / "colmap.log").read_text(errors="replace").splitlines():
        if line.startswith('{"exit_code"'):
            step_times.append(json.loads(line))
    names = camera.validate_scene(out / "colmap/scene")
    result = {
        "engine": camera.info(),
        "report_engine": report["engine"],
        "images_total": report["total"],
        "matched": report["matched"],
        "registered": report["registered"],
        "verified_pairs": report["verified_pairs"],
        "components": {k: len(v) for k, v in report["components"].items()},
        "selected_component": report["selected_component"],
        "scene_validated_images": len(names),
        "seconds_total": round(elapsed, 2),
        "step_seconds": [round(s["seconds"], 2) for s in step_times],
        "cpu_mode": a.cpu,
        "gpu": subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                              capture_output=True, text=True).stdout.strip(),
    }
    (out / "verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not a.cpu:
        gpu_steps = [s for s in report["engine"]["steps"] if s["gpu_requested"]]
        if not gpu_steps or not all(s.get("gpu_observed") or s.get("gpu_log_evidence") for s in gpu_steps):
            sys.exit("GPU use was requested but not observed for every GPU step")


if __name__ == "__main__":
    main()
