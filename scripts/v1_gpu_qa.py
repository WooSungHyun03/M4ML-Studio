"""Genuine new-photo GPU integration, plus interrupted checkpoint/resume.

Only use an isolated running API and its explicit --data directory. No mocks or
scientific substitutes. 1000 steps is integration proof, not convergence proof.
"""

import argparse, base64, hashlib, io, json, time, zipfile
from pathlib import Path
import httpx
import numpy as np
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--data", type=Path, required=True)
parser.add_argument("--photos", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--resume-existing", type=Path)
args = parser.parse_args()
args.output.parent.mkdir(parents=True, exist_ok=True)
c = httpx.Client(base_url=args.url, timeout=600)
headers = {"x-studio-token": c.get("/api/session").json()["token"]}
report = {
    "scope": "actual fresh16 COLMAP/SAM/correction/nondefault1000-checkpoint-resume/TSDF128/PNG; not quality convergence",
    "steps": [],
}


def save():
    temp = args.output.with_suffix(".partial")
    temp.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    temp.replace(args.output)


def post(route, body=None):
    r = c.post("/api" + route, json=body or {}, headers=headers)
    r.raise_for_status()
    return r.json()


def settings(base, group, values):
    r = c.patch(
        "/api" + base + "/task-settings/" + group,
        headers=headers,
        json={"values": values},
    )
    r.raise_for_status()
    return r.json()


def doc():
    return c.get("/api" + base).json()


def wait(job, timeout=900):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        d = doc()
        j = next(j for j in d["jobs"] if j["id"] == job)
        if j["state"] == "completed":
            return d
        if j["state"] in ("failed", "cancelled"):
            raise RuntimeError(j)
        time.sleep(0.3)
    raise TimeoutError(job)


def step(name, **details):
    report["steps"].append({"name": name, **details})
    save()
    print(name, flush=True)


try:
    files = sorted(
        p
        for p in args.photos.iterdir()
        if p.suffix.lower() in (".png", ".jpg", ".jpeg")
    )[:16]
    assert len(files) == 16
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    if args.resume_existing:
        report = json.loads(args.resume_existing.read_text())
        report["previous_test_error"] = report.pop("error", None)
        report["resumed_from_report"] = str(args.resume_existing)
        pid = report["project"]
        base = "/projects/" + pid
        root = args.data.resolve() / "projects" / pid
        assert doc().get(
            "training_partial"
        ), "Resume only the preserved real cancelled checkpoint"
    else:
        project = post(
            "/projects", {"name": "v1 새 사진 GPU 통합 검증", "input_mode": "images"}
        )
        pid = project["id"]
        base = "/projects/" + pid
        report["project"] = pid
        save()
        settings(base, "camera", {"max_image_size": 1600, "max_features": 12000})
        settings(
            base,
            "segmentation",
            {
                "fill_hole_area": 32,
                "sprinkle_removal_area": 16,
                "offload_video_to_cpu": True,
            },
        )
        for p in files:
            with p.open("rb") as f:
                r = c.post(
                    "/api" + base + "/images",
                    headers=headers,
                    files={"file": (p.name, f)},
                )
            r.raise_for_status()
        d = wait(post(base + "/import-complete")["job_id"])
        assert d["colmap_report"]["registered"] == 16
        step("real GPU COLMAP16/16", camera=d["colmap_report"])
        prompt = {
            "gpu": 0,
            "reference": "000001.png",
            "points": [[380.0, 349.0], [868.0, 300.0]],
            "labels": [1, 0],
        }
        session = "v1-latest-prompt"
        post(
            base + "/prompt-session",
            {"reference": prompt["reference"], "session_id": session},
        )
        for revision in range(1, 5):
            post(
                base + "/prompt",
                {**prompt, "session_id": session, "prompt_revision": revision},
            )
        end = time.monotonic() + 900
        while time.monotonic() < end:
            d = doc()
            if d.get("live_prompt", {}).get("status") == "failed":
                raise RuntimeError(d["live_prompt"])
            if d.get("preview", {}).get("prompt_revision") == 4:
                break
            time.sleep(0.3)
        else:
            raise TimeoutError("official SAM latest revision")
        step("official SAM3.1 positive/negative latest-wins", preview=d["preview"])
        d = wait(post(base + "/jobs/sam", {**prompt, "confirmed": True})["job_id"])
        assert len(d["masks"]) == 16 and all(
            m["valid"] for m in d["masks"].values()
        ), d["masks"]
        name = next(iter(d["masks"]))
        m = d["masks"][name]
        png = c.get("/api" + base + "/files/" + m["path"]).content
        image = Image.open(io.BytesIO(png)).convert("L")
        pixels = np.array(image)
        pixels[0, 0] = 255 - pixels[0, 0]
        out = io.BytesIO()
        Image.fromarray(pixels).save(out, format="PNG")
        r = c.put(
            "/api" + base + "/masks/" + name,
            headers=headers,
            json={"png": base64.b64encode(out.getvalue()).decode(), "approve": True},
        )
        r.raise_for_status()
        d = post(base + "/skip-review", {"confirmed": True})
        d = doc()
        assert d["stages"]["review"] == "completed"
        step(
            "actual16-view propagation/manual correction/explicit skip",
            masks=d["masks"],
        )
        settings(
            base,
            "training",
            {
                "iterations": 1000,
                "image_resolution": 400,
                "checkpoint_every": 100,
                "alpha_weight": 0.27,
            },
        )
        settings(base, "mesh", {"mesh_res": 128, "num_cluster": 2})
        job = post(base + "/jobs/train", {"gpu": 0, "confirmed": True})["job_id"]
        root = args.data.resolve() / "projects" / pid
        end = time.monotonic() + 600
        while time.monotonic() < end:
            checkpoints = sorted((root / "runs" / job / "training").glob("chkpnt*.pth"))
            ready = []
            for checkpoint in checkpoints:
                try:
                    with zipfile.ZipFile(checkpoint) as z:
                        if z.testzip() is None:
                            ready.append(checkpoint)
                except (OSError, zipfile.BadZipFile):
                    pass
            if ready:
                break
            assert (
                next(j for j in doc()["jobs"] if j["id"] == job)["state"] == "running"
            )
            time.sleep(0.05)
        else:
            raise TimeoutError("complete checkpoint")
        post(base + "/cancel")
    end = time.monotonic() + 90
    while time.monotonic() < end:
        current = doc()
        if current.get("training_partial") and not any(
            j["state"] in ("pending", "running") for j in current["jobs"]
        ):
            break
        time.sleep(0.2)
    d = doc()
    partial = d["training_partial"]
    checkpoint = root / partial["path"] / f"chkpnt{partial['checkpoint']}.pth"
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    snapshot = partial["fingerprint"]["settings"]["values"]
    settings(base, "training", {**snapshot, "alpha_weight": 0.4})
    r = c.post(
        "/api" + base + "/jobs/train",
        headers=headers,
        json={"gpu": 0, "confirmed": True, "resume": True},
    )
    assert r.status_code == 422, r.text
    settings(base, "training", snapshot)
    resumed = post(base + "/jobs/train", {"gpu": 0, "confirmed": True, "resume": True})[
        "job_id"
    ]
    d = wait(resumed)
    end = time.monotonic() + 600
    while time.monotonic() < end:
        d = doc()
        if d["stages"]["mesh"] == "completed" and not any(
            j["state"] in ("pending", "running") for j in d["jobs"]
        ):
            break
        if any(j["stage"] == "mesh" and j["state"] == "failed" for j in d["jobs"]):
            raise RuntimeError(d["jobs"])
        time.sleep(0.5)
    assert (
        d["stages"]["mesh"] == "completed"
        and d["training"]["iterations"] == 1000
        and d["training"]["resumed_from"] == partial["checkpoint"]
    )
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == digest
    assert d["mesh"]["colors"] and d["mesh"]["color_roundtrip_max_error"] < 1 / 255
    step(
        "original1000 resume/nondefault alpha.27/automatic colored TSDF128",
        checkpoint=partial["checkpoint"],
        training=d["training"],
        mesh=d["mesh"],
        mismatch_status=422,
    )
    post(base + "/live-render/start", {"gpu": 0})
    info = c.get("/api" + base + "/live-render").json()
    cam = info["model"]["cameras"][0]
    c2w = np.eye(4)
    c2w[:3, :3] = cam["rotation"]
    c2w[:3, 3] = cam["position"]
    view = np.diag([1, -1, -1, 1]) @ np.linalg.inv(c2w)
    r = c.post(
        "/api" + base + "/live-render/frame",
        headers=headers,
        json={
            "view": view.T.reshape(-1).tolist(),
            "width": 640,
            "height": 480,
            "fovy": 0.7,
            "mode": "rgb",
            "encoding": "png",
            "znear": 0.01,
            "zfar": 1000,
        },
    )
    r.raise_for_status()
    Image.open(io.BytesIO(r.content)).verify()
    args.output.with_suffix(".png").write_bytes(r.content)
    post(base + "/live-render/stop")
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files} == hashes
    step(
        "actual native CUDA frame, source photos preserved",
        frame_bytes=len(r.content),
        source_sha256=hashes,
    )
    report["passed"] = True
    save()
except Exception as e:
    report["error"] = repr(e)
    save()
    raise
finally:
    c.close()
