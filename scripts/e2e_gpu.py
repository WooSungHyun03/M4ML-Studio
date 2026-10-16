#!/usr/bin/env python3
"""Real end-to-end GPU acceptance run through the HTTP API (no mocks).

Start a separate server on an isolated data directory first, e.g.
  STUDIO_DATA=evidence/e2e-0.3/data STUDIO_PORT=8767 ./scripts/start.sh
then
  .runtime/bin/python scripts/e2e_gpu.py --url http://127.0.0.1:8767 \
      --images datasets/south-building-full/images --count 24 \
      --fixture evidence/m4ml-fixtures/registered-colmap --output evidence/e2e-0.3/result.json

Checks (each recorded in the JSON report):
  A  images → GPU camera registration (GPU use observed) → live clicks via the persistent
     selection session (latest-wins, latency) → propagation → manual fix + skip-rest →
     reconstruction (pause after first checkpoint, resume from it) → automatic coloured
     3D model → PLY/GLB download and colour verification.
  B  imported calibration (no camera registration) → live click → propagation → train → model.
  C  imported calibration + masks (no registration, no segmentation) → train → model.
"""

import argparse, base64, io, json, sys, time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.doctor import atomic_json  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8767")
ap.add_argument("--images", type=Path, required=True)
ap.add_argument("--count", type=int, default=24)
ap.add_argument("--fixture", type=Path, required=True)
ap.add_argument("--output", type=Path, required=True)
ap.add_argument("--iterations", type=int, default=6000)
ap.add_argument("--mesh-res", type=int, default=512, choices=(256, 512, 1024))
ap.add_argument("--skip-pause", action="store_true", help="설치 후 짧은 연결 시험용; 체크포인트 재개를 검증하지 않음")
ap.add_argument("--only", default="ABC")
a = ap.parse_args()
if not a.only or set(a.only) - set("ABC"):
    ap.error("--only must select at least one of A, B, C")
if "A" in a.only and not a.skip_pause and a.iterations < 3000:
    ap.error("Mode A pause/resume needs at least3000 iterations; use --skip-pause for an explicit short smoke")
c = httpx.Client(base_url=a.url, timeout=600)
H = {"x-studio-token": c.get("/api/session").json()["token"]}
report = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "url": a.url}


def save():
    atomic_json(a.output, report)


def post(path, data=None):
    r = c.post("/api" + path, json=data or {}, headers=H)
    if r.status_code >= 400:
        raise RuntimeError(f"{path}: {r.status_code} {r.text}")
    return r.json()


def doc(pid):
    return c.get(f"/api/projects/{pid}").json()


def running(d):
    return next((j for j in d.get("jobs", []) if j["state"] == "running"), None)


def wait(pid, stage, timeout=3600, allow_states=("completed",)):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        d = doc(pid)
        if not running(d):
            if d["stages"][stage] in allow_states:
                return d
            last = d["jobs"][0] if d["jobs"] else None
            if last and last["state"] in ("failed", "cancelled"):
                raise RuntimeError(f"{stage} job {last['state']}: {last['message']}")
        time.sleep(1)
    raise TimeoutError(stage)


def live_clicks(pid, frame, sequence):
    """Send several prompt revisions quickly; return latency and published revision."""
    session = f"e2e-{pid[:8]}-{int(time.time())}"
    post(f"/projects/{pid}/prompt-session", {"reference": frame, "session_id": session})
    sent = []
    t0 = time.monotonic()
    for rev, (points, labels) in enumerate(sequence, 1):
        post(f"/projects/{pid}/prompt", {"gpu": 0, "reference": frame, "session_id": session,
                                         "prompt_revision": rev, "points": points, "labels": labels})
        sent.append(time.monotonic() - t0)
        time.sleep(0.05)
    published = []
    while time.monotonic() - t0 < 600:
        d = doc(pid)
        live = d.get("live_prompt", {})
        prev = d.get("preview") or {}
        if prev.get("session_id") == session and prev.get("prompt_revision") not in published:
            published.append(prev.get("prompt_revision"))
        if live.get("status") == "failed":
            raise RuntimeError(live.get("error"))
        if live.get("status") == "ready" and prev.get("prompt_revision") == len(sequence):
            break
        time.sleep(0.1)
    total = time.monotonic() - t0
    # a single follow-up click on a warm session measures interactive latency
    rev = len(sequence) + 1
    points, labels = sequence[-1]
    t1 = time.monotonic()
    post(f"/projects/{pid}/prompt", {"gpu": 0, "reference": frame, "session_id": session,
                                     "prompt_revision": rev, "points": points + [[points[0][0] + 5, points[0][1] + 5]],
                                     "labels": labels + [1]})
    while time.monotonic() - t1 < 120:
        d = doc(pid)
        if d.get("preview", {}).get("prompt_revision") == rev and d["live_prompt"]["status"] == "ready":
            break
        time.sleep(0.05)
    warm = time.monotonic() - t1
    d = doc(pid)
    return {
        "revisions_sent": len(sequence) + 1,
        "published_revisions_observed": published,
        "final_revision": d["preview"]["prompt_revision"],
        "first_burst_seconds": round(total, 2),
        "warm_click_roundtrip_seconds": round(warm, 3),
        "engine_seconds_last": d["live_prompt"].get("seconds"),
        "preview_coverage": d["preview"].get("coverage"),
        "jobs_created_for_clicks": sum(1 for j in d["jobs"] if j["stage"] == "preview"),
    }, d["prompt"]


def verify_downloads(pid, d):
    from plyfile import PlyData
    import numpy as np
    from studio.mesh import glb_colors

    mesh = d["mesh"]
    ply_bytes = c.get(f"/api/projects/{pid}/files/{mesh['path']}/fuse_post.ply").content
    glb_bytes = c.get(f"/api/projects/{pid}/files/{mesh['path']}/{mesh.get('preview_name', 'preview.glb')}").content
    ply = PlyData.read(io.BytesIO(ply_bytes))["vertex"]
    rgb = np.stack([ply["red"], ply["green"], ply["blue"]], 1).astype(float) / 255
    tmp = a.output.parent / f"{pid}.glb"
    tmp.write_bytes(glb_bytes)
    glb = glb_colors(tmp)
    return {
        "ply_vertices": int(len(ply)),
        "ply_rgb_std": float(rgb.std()),
        "ply_rgb_mean": rgb.mean(0).round(4).tolist(),
        "ply_non_gray_fraction": float((np.ptp(rgb, axis=1) > 0.04).mean()),
        "glb_color_vertices": int(len(glb)) if glb is not None else 0,
        "glb_present": glb is not None,
        "bytes": {"ply": len(ply_bytes), "glb": len(glb_bytes)},
    }


def train_with_pause(pid):
    out = {}
    post(f"/projects/{pid}/jobs/train", {"gpu": 0, "iterations": a.iterations, "mesh_res": a.mesh_res, "confirmed": True})
    t0 = time.monotonic()
    if a.skip_pause:
        d = wait(pid, "mesh")
        return {"scope": "explicit training/mesh smoke; checkpoint pause/resume not tested",
                "iterations": a.iterations, "mesh_res": a.mesh_res,
                "mesh": d["mesh"], "downloads": verify_downloads(pid, d),
                "seconds": round(time.monotonic() - t0, 1)}, d
    while True:  # wait past the first checkpoint (2,500) and pause
        d = doc(pid)
        j = running(d)
        if j and j["stage"] == "train" and (j.get("current") or 0) >= 2700:
            break
        if not j and time.monotonic() - t0 > 30:
            raise RuntimeError(f"training ended before pause: {d['jobs'][0]}")
        time.sleep(1)
    out["paused_at_iteration"] = j["current"]
    post(f"/projects/{pid}/cancel")
    d = wait(pid, "train", allow_states=("cancelled",))
    out["partial"] = d.get("training_partial")
    assert d["training_partial"]["checkpoint"] == 2500, d.get("training_partial")
    post(f"/projects/{pid}/jobs/train", {"gpu": 0, "iterations": a.iterations, "mesh_res": a.mesh_res, "confirmed": True, "resume": True})
    d = wait(pid, "train")
    out["resumed_from"] = d["training"].get("resumed_from")
    out["gaussians"] = d["training"]["gaussians"]
    d = wait(pid, "mesh")
    out["mesh"] = {k: d["mesh"].get(k) for k in ("vertices", "triangles", "colors", "color_roundtrip_max_error", "engine")}
    out["downloads"] = verify_downloads(pid, d)
    out["seconds"] = round(time.monotonic() - t0, 1)
    return out, d


def import_fixture(pid):
    for f in sorted(a.fixture.rglob("*")):
        if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".bin", ".txt"} and "stereo" not in f.parts:
            with f.open("rb") as stream:
                r = c.post(f"/api/projects/{pid}/import-files",
                           files={"file": ("fixture/" + f.relative_to(a.fixture).as_posix(), stream)}, headers=H)
                r.raise_for_status()


# ------------------------------------------------------------------ Mode A
if "A" in a.only:
    t = time.monotonic()
    pid = post("/projects", {"name": "E2E 0.3 Mode A", "input_mode": "images"})["id"]
    files = sorted(a.images.glob("*.JPG")) + sorted(a.images.glob("*.jpg")) + sorted(a.images.glob("*.png"))
    for f in files[: a.count]:
        with f.open("rb") as s:
            c.post(f"/api/projects/{pid}/images", files={"file": (f.name, s)}, headers=H).raise_for_status()
    r = post(f"/projects/{pid}/import-complete")
    assert r.get("job_id"), r
    d = wait(pid, "colmap")
    rep = d["colmap_report"]
    report["A"] = {"id": pid, "camera": {
        "registered": rep["registered"], "total": rep["total"], "matched": rep["matched"],
        "engine": rep.get("engine"), "seconds": round(time.monotonic() - t, 1)}}
    gpu_steps = [s for s in rep["engine"]["steps"] if s["gpu_requested"]]
    assert gpu_steps and all(s.get("gpu_observed") for s in gpu_steps), rep["engine"]
    save()
    frame = next(i["name"] for i in rep["images"] if i["registered"])
    from PIL import Image  # noqa: E402

    w, h = (int(v) for v in Image.open(io.BytesIO(c.get(f"/api/projects/{pid}/files/{d['scene']}/images/{frame}").content)).size)
    cx, cy = w * 0.42, h * 0.45
    seq = [([[cx, cy]], [1]), ([[cx, cy], [w * 0.92, h * 0.1]], [1, 0]),
           ([[cx, cy], [w * 0.92, h * 0.1], [cx - w * 0.05, cy + h * 0.05]], [1, 0, 1]),
           ([[cx, cy], [w * 0.92, h * 0.1], [cx - w * 0.05, cy + h * 0.05], [w * 0.5, h * 0.95]], [1, 0, 1, 0])]
    report["A"]["live_selection"], prompt = live_clicks(pid, frame, seq)
    save()
    post(f"/projects/{pid}/jobs/sam", {"gpu": 0, "reference": prompt["reference"], "points": prompt["points"],
                                      "labels": prompt["labels"], "confirmed": True})
    d = wait(pid, "sam")
    report["A"]["masks"] = {"count": len(d["masks"]), "valid": sum(m["valid"] for m in d["masks"].values()),
                            "warnings": sum(bool(m.get("warnings")) for m in d["masks"].values())}
    name = sorted(d["masks"])[1]
    png = c.get(f"/api/projects/{pid}/files/{d['masks'][name]['path']}").content
    r = c.put(f"/api/projects/{pid}/masks/{name}", json={"png": base64.b64encode(png).decode(), "approve": True}, headers=H)
    r.raise_for_status()
    post(f"/projects/{pid}/skip-review", {"confirmed": True})
    d = doc(pid)
    report["A"]["review"] = {s: sum(m["status"] == s for m in d["masks"].values()) for s in ("manual", "approved", "skipped", "generated")}
    save()
    report["A"]["reconstruction"], d = train_with_pause(pid)
    report["A"]["seconds_total"] = round(time.monotonic() - t, 1)
    save()

# ------------------------------------------------------------------ Mode B
if "B" in a.only:
    pid = post("/projects", {"name": "E2E 0.3 Mode B", "input_mode": "colmap"})["id"]
    import_fixture(pid)
    r = post(f"/projects/{pid}/commit-import", {"with_masks": False})
    assert r["committed"], r
    d = doc(pid)
    assert not any(j["stage"] == "colmap" for j in d["jobs"])
    frame = sorted(d["masks"] or [i["name"] for i in d["colmap_report"]["images"] if i["registered"]])[0]
    report["B"] = {"id": pid, "camera_jobs": 0}
    report["B"]["live_selection"], prompt = live_clicks(pid, frame, [([[380.0, 349.0]], [1]), ([[380.0, 349.0], [868.0, 300.0]], [1, 0])])
    post(f"/projects/{pid}/jobs/sam", {"gpu": 0, "reference": prompt["reference"], "points": prompt["points"], "labels": prompt["labels"], "confirmed": True})
    d = wait(pid, "sam")
    post(f"/projects/{pid}/skip-review", {"confirmed": True})
    post(f"/projects/{pid}/jobs/train", {"gpu": 0, "iterations": 1000, "mesh_res": 256, "confirmed": True})
    d = wait(pid, "mesh")
    report["B"]["masks"] = len(d["masks"])
    report["B"]["mesh"] = {k: d["mesh"].get(k) for k in ("vertices", "triangles", "colors")}
    report["B"]["downloads"] = verify_downloads(pid, d)
    save()

# ------------------------------------------------------------------ Mode C
if "C" in a.only:
    pid = post("/projects", {"name": "E2E 0.3 Mode C", "input_mode": "colmap_masks"})["id"]
    import_fixture(pid)
    r = post(f"/projects/{pid}/commit-import", {"with_masks": True, "skip_review": True})
    assert r["committed"], r
    d = doc(pid)
    assert not any(j["stage"] in ("colmap", "sam", "preview") for j in d["jobs"])
    post(f"/projects/{pid}/jobs/train", {"gpu": 0, "iterations": 1000, "mesh_res": 256, "confirmed": True})
    d = wait(pid, "mesh")
    report["C"] = {"id": pid, "camera_jobs": 0, "segmentation_jobs": 0,
                   "mesh": {k: d["mesh"].get(k) for k in ("vertices", "triangles", "colors")},
                   "downloads": verify_downloads(pid, d)}
    save()

report["status"] = "PASS"
report["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
save()
print(json.dumps(report, ensure_ascii=False, indent=2))
