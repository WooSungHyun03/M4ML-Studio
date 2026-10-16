"""Repeat real SAM local correction/train/automatic TSDF on a verified scene fixture.

The fixture must explicitly reference a completed genuine E2E source project.
This is separate from the original full browser import/COLMAP/30K run.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from studio.doctor import atomic_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    client = httpx.Client(base_url="http://127.0.0.1:8765", timeout=30)
    token = client.get("/api/session").json()["token"]
    headers = {"x-studio-token": token}
    base = f"/api/projects/{args.project}"

    def get():
        response = client.get(base)
        response.raise_for_status()
        return response.json()

    def post(path, body):
        response = client.post(base + path, json=body, headers=headers)
        response.raise_for_status()
        return response.json()

    def wait(job_id):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            job = next(j for j in get()["jobs"] if j["id"] == job_id)
            if job["state"] == "completed":
                return job
            if job["state"] in ("failed", "cancelled"):
                raise RuntimeError(job)
            time.sleep(0.5)
        raise TimeoutError(job_id)

    before = get()
    assert before.get(
        "source_verified_project"
    ), "Requires an explicit genuine scene fixture"
    prompt = before["prompt"]
    request = {**prompt, "gpu": 0}
    preview = post("/jobs/preview", request)["job_id"]
    wait(preview)
    sam = post("/jobs/sam", {**request, "confirmed": True, "radius": 2})["job_id"]
    wait(sam)
    after = get()
    frames = client.get(base + f"/files/runs/{sam}/predictions/frames.json").json()
    ref = next(f["frame_index"] for f in frames if f["name"] == prompt["reference"])
    allowed = {f["name"] for f in frames if abs(f["frame_index"] - ref) <= 2}
    updated = []
    for name, item in before["masks"].items():
        current = after["masks"][name]
        if item["status"] in ("manual", "approved", "skipped") or name not in allowed:
            assert (
                current["path"] == item["path"] and current["sha256"] == item["sha256"]
            ), name
        elif current["path"] != item["path"]:
            updated.append(name)
    assert updated and set(updated) <= allowed
    skipped = post("/skip-review", {"confirmed": True})
    assert skipped["stages"]["review"] == "completed"
    training = post(
        "/jobs/train", {"gpu": 0, "confirmed": True, "iterations": 100, "mesh_res": 128}
    )["job_id"]
    train_job = wait(training)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        result = get()
        if result["stages"]["mesh"] == "completed":
            break
        if result["stages"]["mesh"] in ("failed", "cancelled"):
            raise RuntimeError(result["jobs"][0])
        time.sleep(0.5)
    else:
        raise TimeoutError("automatic TSDF")
    assert all(s == "completed" for s in result["stages"].values())
    assert result["mesh"]["vertices"] > 0 and result["mesh"]["triangles"] > 0
    response = client.get(base + "/files/" + result["mesh"]["path"] + "/fuse_post.ply")
    response.raise_for_status()
    assert hashlib.sha256(response.content).hexdigest() == result["mesh"]["sha256"]
    atomic_json(
        args.output,
        {
            "status": "PASS",
            "source_project": before["source_verified_project"],
            "project": args.project,
            "preview_job": preview,
            "local_propagation_job": sam,
            "local_expected_names": sorted(allowed),
            "updated_unreviewed_names": updated,
            "approved_and_outside_masks_preserved": True,
            "train_job": train_job,
            "mesh": result["mesh"],
            "stages": result["stages"],
        },
    )
    response = client.delete(base, headers=headers)
    response.raise_for_status()
    assert response.json()["archived"]
    client.close()
    print(
        "PASS real cold-runtime API: SAM local propagation preserves reviewed masks, explicit100 train, automatic TSDF, export hash and soft archive."
    )


if __name__ == "__main__":
    main()
