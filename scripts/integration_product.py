"""Real local P0 integration; fixture must contain genuine calibrated photos/masks."""

import argparse, base64, json, sys, time
from pathlib import Path
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.doctor import atomic_json

p = argparse.ArgumentParser()
p.add_argument("--url", default="http://127.0.0.1:8767")
p.add_argument("--fixture", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
args = p.parse_args()
c = httpx.Client(base_url=args.url, timeout=240)
token = c.get("/api/session").json()["token"]
headers = {"x-studio-token": token}
report = {}


def req(path, data=None):
    r = c.post("/api" + path, json=data or {}, headers=headers)
    r.raise_for_status()
    return r.json()


def doc(pid):
    return c.get("/api/projects/" + pid).json()


def wait(pid, stage=None, timeout=300):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        d = doc(pid)
        active = next((j for j in d["jobs"] if j["state"] == "running"), None)
        if not active and (not stage or d["stages"][stage] == "completed"):
            return d
        if not active and d["jobs"] and d["jobs"][0]["state"] == "failed":
            raise RuntimeError(d["jobs"][0])
        time.sleep(0.5)
    raise TimeoutError((pid, stage, doc(pid)))


def create(mode):
    return req("/projects", {"name": "M4ML 실제 검증 " + mode, "input_mode": mode})[
        "id"
    ]


def import_files(pid):
    for f in args.fixture.rglob("*"):
        if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".bin", ".txt"}:
            with f.open("rb") as stream:
                r = c.post(
                    f"/api/projects/{pid}/import-files",
                    files={
                        "file": (
                            "fixture/" + f.relative_to(args.fixture).as_posix(),
                            stream,
                        )
                    },
                    headers=headers,
                )
                r.raise_for_status()


def train(pid):
    before = doc(pid)
    assert before["stages"]["review"] == "completed"
    req(
        f"/projects/{pid}/jobs/train",
        {"gpu": 0, "iterations": 100, "mesh_res": 256, "confirmed": True},
    )
    d = wait(pid, "mesh", 600)
    assert d["mesh"]["colors"] and d["mesh"]["color"]["present"]
    assert d["mesh"]["color_roundtrip_max_error"] < 1 / 255
    return {
        "id": pid,
        "stages": d["stages"],
        "gaussians": d["training"]["gaussians"],
        "mesh": d["mesh"],
        "provenance": d.get("stage_provenance"),
    }


# B: genuine pre-registered bundle, no SfM. Later revision supersedes a running old revision.
pid = create("colmap")
import_files(pid)
r = req(f"/projects/{pid}/commit-import", {"with_masks": False})
assert r["committed"], r
assert not doc(pid)["jobs"]
session = "real-product-race"
frame = "000001.png"
req(f"/projects/{pid}/prompt-session", {"reference": frame, "session_id": session})
base = {"gpu": 0, "reference": frame, "session_id": session}
req(
    f"/projects/{pid}/prompt",
    {**base, "prompt_revision": 1, "points": [[380.0, 349.0]], "labels": [1]},
)
for _ in range(100):
    if any(j["state"] == "running" for j in doc(pid)["jobs"]):
        break
    time.sleep(0.1)
points = [[380.0, 349.0], [868.0, 300.0]]
for rev in range(2, 7):
    points[0][0] = 380.0 + rev * 0.1
    req(
        f"/projects/{pid}/prompt",
        {**base, "prompt_revision": rev, "points": points, "labels": [1, 0]},
    )
for _ in range(600):
    d = doc(pid)
    if d.get("live_prompt", {}).get("status") == "failed":
        raise RuntimeError(d["live_prompt"])
    if d.get("preview", {}).get("prompt_revision") == 6 and not any(
        j["state"] == "running" for j in d["jobs"]
    ):
        break
    time.sleep(0.5)
else:
    raise TimeoutError("Latest SAM revision did not complete")
assert d["preview"]["session_id"] == session
assert d["prompt"]["points"] == points
report["B_prompt_race"] = {
    "id": pid,
    "preview": d["preview"],
    "jobs": [{k: j[k] for k in ("id", "state", "stage", "message")} for j in d["jobs"]],
}
atomic_json(args.output, report)
req(
    f"/projects/{pid}/jobs/sam",
    {
        "gpu": 0,
        "reference": frame,
        "points": points,
        "labels": [1, 0],
        "confirmed": True,
    },
)
d = wait(pid, "sam")
assert len(d["masks"]) == 16
name = next(iter(d["masks"]))
png = c.get("/api/projects/" + pid + "/files/" + d["masks"][name]["path"]).content
r = c.put(
    f"/api/projects/{pid}/masks/{name}",
    json={"png": base64.b64encode(png).decode(), "approve": True},
    headers=headers,
)
r.raise_for_status()
req(f"/projects/{pid}/skip-review", {"confirmed": True})
report["B"] = train(pid)
atomic_json(args.output, report)
# C: no SAM or SfM jobs, explicit imported-mask review skip, genuine train/automatic TSDF.
pid = create("colmap_masks")
import_files(pid)
r = req(f"/projects/{pid}/commit-import", {"with_masks": True, "skip_review": True})
assert r["committed"], r
assert not doc(pid)["jobs"]
report["C"] = train(pid)
atomic_json(args.output, report)
# A regression: imported photos -> new real COLMAP -> new real SAM -> original train -> color mesh.
pid = create("images")
for f in sorted((args.fixture / "images").glob("*.png")):
    with f.open("rb") as stream:
        r = c.post(
            f"/api/projects/{pid}/images",
            files={"file": (f.name, stream)},
            headers=headers,
        )
        r.raise_for_status()
req(f"/projects/{pid}/import-complete")
d = wait(pid, "colmap")
assert d["colmap_report"]["registered"] >= 2
req(
    f"/projects/{pid}/jobs/preview",
    {
        "gpu": 0,
        "reference": frame,
        "points": [[380.0, 349.0], [868.0, 300.0]],
        "labels": [1, 0],
    },
)
wait(pid)
req(
    f"/projects/{pid}/jobs/sam",
    {
        "gpu": 0,
        "reference": frame,
        "points": [[380.0, 349.0], [868.0, 300.0]],
        "labels": [1, 0],
        "confirmed": True,
    },
)
wait(pid, "sam")
req(f"/projects/{pid}/skip-review", {"confirmed": True})
report["A"] = train(pid)
report["status"] = "PASS"
atomic_json(args.output, report)
print(json.dumps(report, ensure_ascii=False))
