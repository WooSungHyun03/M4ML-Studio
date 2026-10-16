"""Audit an actual completed local project; never manufactures pipeline outputs."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from PIL import Image
from plyfile import PlyData
from studio.colmap import validate_scene
from studio.doctor import atomic_json, sha256
from studio.mesh import validate_mesh
from studio.sam31 import validate_mask
from studio.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    store = Store(args.data)
    p = store.get(args.project)
    root = store.path(p["id"])
    assert all(s == "completed" for s in p["stages"].values()), p["stages"]
    assert p["target_confirmed"]
    for item in p["images"]:
        assert sha256(root / item["path"]) == item["normalized_sha256"]
        assert (
            sha256(root / "input/snapshots" / (Path(item["name"]).stem + ".original"))
            == item["source_sha256"]
        )
    names = validate_scene(root / p["scene"])
    selected = {
        row["name"] for row in p["colmap_report"]["images"] if row["registered"]
    }
    assert names == selected == set(p["masks"])
    statuses = {}
    mask_report = {}
    for name, item in p["masks"].items():
        with Image.open(root / p["scene"] / "images" / name) as image:
            stats = validate_mask(root / item["path"], image.size)
        assert stats["sha256"] == item["sha256"]
        assert item["status"] in ("approved", "manual", "skipped")
        statuses[item["status"]] = statuses.get(item["status"], 0) + 1
        mask_report[name] = stats
    training = p["training"]
    ply = (
        root
        / training["path"]
        / "point_cloud"
        / f"iteration_{training['iterations']}"
        / "point_cloud.ply"
    )
    vertices = PlyData.read(ply)["vertex"]
    assert len(vertices) == training["gaussians"]
    for key in vertices.data.dtype.names:
        assert np.isfinite(vertices[key]).all(), key
    mesh = validate_mesh(root / p["mesh"]["path"] / "fuse_post.ply")
    assert mesh["sha256"] == p["mesh"]["sha256"]
    import trimesh

    preview = trimesh.load(
        root / p["mesh"]["path"] / "preview.glb", force="mesh", process=False
    )
    assert len(preview.faces) == mesh["triangles"]
    report = {
        "status": "PASS",
        "project": p["id"],
        "name": p["name"],
        "stages": p["stages"],
        "registered": len(names),
        "review_status_counts": statuses,
        "mask_validation": mask_report,
        "iterations": training["iterations"],
        "gaussian_vertices": len(vertices),
        "gaussian_fields": vertices.data.dtype.names,
        "gaussian_sha256": sha256(ply),
        "mesh": mesh,
        "preview_sha256": sha256(root / p["mesh"]["path"] / "preview.glb"),
        "jobs": [
            {k: j[k] for k in ("id", "stage", "state", "exit_code", "created", "ended")}
            for j in store.jobs(p["id"])
        ],
    }
    atomic_json(args.output, report)
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ("mask_validation", "jobs")},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
