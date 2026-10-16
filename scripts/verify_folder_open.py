#!/usr/bin/env python3
"""Real "새 프로젝트 → 폴더" check through the API (no mocks; isolated data directory).

  STUDIO_DATA=<tmp> .runtime/bin/python scripts/verify_folder_open.py OUT.json FOLDER...

For every folder: scan → open → check what was reused, which stage is next, that the
source folder was not modified (hash of every file before/after) and that no completed
stage is recomputed (no jobs except the automatic camera registration for photo-only input).
"""

import hashlib, json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
assert os.environ.get("STUDIO_DATA"), "set STUDIO_DATA to an isolated directory"
from fastapi.testclient import TestClient  # noqa: E402
from studio.api import app  # noqa: E402


def tree_hash(folder):
    h = hashlib.sha256()
    for p in sorted(Path(folder).rglob("*")):
        if p.is_file():
            h.update(p.relative_to(folder).as_posix().encode())
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


out, folders = Path(sys.argv[1]), sys.argv[2:]
report = {}
with TestClient(app) as c:
    H = {"x-studio-token": c.get("/api/session").json()["token"]}
    for folder in folders:
        before = tree_hash(folder)
        t = time.time()
        scan = c.post("/api/scan-folder", json={"path": folder}, headers=H).json()
        r = c.post("/api/projects/from-folder", json={"path": folder}, headers=H)
        body = r.json()
        if r.status_code != 200:
            report[folder] = {"status": r.status_code, "error": body}
            continue
        p = body["project"]
        # wait for an automatic job (photo-only folders start camera registration)
        for _ in range(900):
            d = c.get(f"/api/projects/{p['id']}").json()
            if not any(j["state"] == "running" for j in d.get("jobs", [])):
                break
            time.sleep(1)
        report[folder] = {
            "recommendation": scan["recommendation"],
            "mode": d.get("input_mode"),
            "stages": d["stages"],
            "reused": body["reused"],
            "skipped": body["skipped"],
            "jobs": [(j["stage"], j["state"]) for j in d.get("jobs", [])],
            "training": d.get("training") and {k: d["training"][k] for k in ("iterations", "gaussians")},
            "training_partial": d.get("training_partial") and d["training_partial"]["checkpoint"],
            "mesh": d.get("mesh") and {k: d["mesh"].get(k) for k in ("vertices", "triangles", "colors")},
            "masks": len(d.get("masks", {})),
            "source_unchanged": tree_hash(folder) == before,
            "seconds": round(time.time() - t, 1),
        }
        print(folder, json.dumps(report[folder], ensure_ascii=False)[:600])
out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
