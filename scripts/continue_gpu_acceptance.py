"""Resume only an agent-owned interrupted acceptance project; never recreate its camera/SAM work."""
import argparse
import json
from pathlib import Path
import time

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--url", required=True)
ap.add_argument("--report", type=Path, required=True)
ap.add_argument("--data", type=Path, required=True)
args = ap.parse_args()
report = json.loads(args.report.read_text())
pid = report["A"]["id"]
c = httpx.Client(base_url=args.url, timeout=90)
headers = {"x-studio-token": c.get("/api/session").json()["token"]}


def save():
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def doc():
    r = c.get(f"/api/projects/{pid}"); r.raise_for_status(); return r.json()


def post(action, body=None):
    r = c.post(f"/api/projects/{pid}/" + action, json=body or {}, headers=headers)
    r.raise_for_status(); return r.json()


def wait_idle(timeout=120):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        p = doc()
        if not any(j["state"] == "running" for j in p["jobs"]): return p
        time.sleep(.5)
    raise TimeoutError("acceptance job still running")


p = wait_idle()
partial = p["training_partial"]
assert partial["fingerprint"]["dataset"]["schema_version"] == 1
report["recovery"] = {"original_cancel_failure": "500 SQLite write-lock starvation (retained initial log)",
                      "recovered_checkpoint": partial["checkpoint"]}
save()
body = {"gpu": 0, "iterations": partial["iterations"], "mesh_res": 1024, "confirmed": True, "resume": True}
# A same-path, still-decodable photo edit must reject the resume before original train.py.
root = (args.data / "projects" / pid).resolve()
name = sorted(p["masks"])[0]
photo = root / p["scene"] / "images" / name
original = photo.read_bytes()
try:
    photo.write_bytes(original + b"acceptance-identity-change")
    post("jobs/train", body)
    rejected = wait_idle()
    assert rejected["jobs"][0]["state"] == "failed"
    assert "검증 기록" in rejected["jobs"][0]["message"] or "바뀌" in rejected["jobs"][0]["message"]
    report["recovery"]["changed_photo_rejected"] = rejected["jobs"][0]["message"]
finally:
    photo.write_bytes(original)
save()
post("jobs/train", body)
checkpoint = partial["checkpoint"]
end = time.monotonic() + 600
while time.monotonic() < end:
    p = doc()
    active = next((j for j in p["jobs"] if j["state"] == "running"), None)
    if active and (active.get("current") or 0) >= checkpoint + 300: break
    if not active: raise RuntimeError(p["jobs"][0])
    time.sleep(.5)
else: raise TimeoutError("resumed iterations not observed")
t = time.monotonic()
post("cancel")
report["recovery"]["cancel_api_seconds"] = round(time.monotonic() - t, 3)
p = wait_idle()
assert p["jobs"][0]["state"] == "cancelled", p["jobs"][0]
report["recovery"]["second_checkpoint"] = p["training_partial"]["checkpoint"]
save()
post("jobs/train", body)
end = time.monotonic() + 7200
while time.monotonic() < end:
    p = doc()
    active = next((j for j in p["jobs"] if j["state"] == "running"), None)
    if not active and p["stages"]["mesh"] == "completed": break
    if not active and p["jobs"][0]["state"] == "failed": raise RuntimeError(p["jobs"][0])
    time.sleep(2)
else: raise TimeoutError("full training or mesh did not complete")
assert p["training"]["iterations"] == 30000 and p["mesh"]["mesh_res"] == 1024
assert p["mesh"]["colors"] and p["mesh"]["color_roundtrip_max_error"] < 1 / 255
report["A"]["reconstruction"] = {"training": p["training"], "mesh": p["mesh"]}
report["status"] = "PASS"
save()
print(json.dumps(report, ensure_ascii=False, indent=2))
