"""Folder analysis for "새 프로젝트 → 폴더 선택": what exists, is it valid, where to start.

Pure and read-only: never writes into the scanned folder, never imports torch/CUDA, and
never trusts file presence alone. Each finding carries a ``valid`` flag plus the reason.

Recognised content (any reasonable layout, bounded depth):
  * multi-view photos (images/, input/, or any folder with ≥2 photos)
  * COLMAP sparse models (.bin or .txt: cameras/images/points3D), registered images,
    whether cameras are already undistorted (PINHOLE / SIMPLE_PINHOLE)
  * binary object masks (mask/, masks/, …) matched to registered images by stem
  * 2DGS / Object-Aware training outputs (cfg_args + point_cloud/iteration_N) and
    checkpoints (chkpntN.pth); matched to THIS dataset through cameras.json names and
    camera centres compared with the COLMAP poses (not just by folder name)
  * triangle meshes (.ply with faces, .glb) and whether they carry vertex colours
  * an M4ML Studio project manifest
"""

from __future__ import annotations

import json
import os
import re
import struct
from pathlib import Path

import numpy as np

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
MASK_DIR_NAMES = {
    "mask",
    "masks",
    "object_mask",
    "object_masks",
    "alpha",
    "segmentation",
}
SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".cache",
    "renders",
    "gt",
    "vis",
    "depth",
    "normal",
    "test",
}
MAX_DEPTH = 7
MAX_ENTRIES = 60000


class ScanLimit(ValueError):
    pass


# --------------------------------------------------------------------------- walking
def _walk(root: Path):
    """Bounded directory walk → {dir: [file names]}; refuses absurdly large trees."""
    out, count = {}, 0
    for current, dirs, files in os.walk(root, followlinks=False):
        depth = len(Path(current).relative_to(root).parts)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS) if depth < MAX_DEPTH else []
        count += len(files) + len(dirs)
        if count > MAX_ENTRIES:
            raise ScanLimit("폴더 안의 파일이 너무 많습니다. 프로젝트 데이터만 들어 있는 폴더를 선택하세요.")
        out[Path(current)] = files
    return out


def _is_mask_dir(path: Path, root: Path):
    parts = [p.lower() for p in path.relative_to(root).parts]
    return any(p in MASK_DIR_NAMES or p.endswith("_mask") or p.endswith("_masks") for p in parts)


def _in_training_output(path: Path, root: Path):
    parts = path.relative_to(root).parts
    return any(p == "point_cloud" or p.startswith("ours_") or p == "train" and i > 0 for i, p in enumerate(parts))


def _image_size(path: Path):
    from PIL import Image

    with Image.open(path) as im:  # header only
        return im.size


# --------------------------------------------------------------------------- COLMAP models
def _loader():
    import importlib.util

    from studio.doctor import ROOT

    spec = importlib.util.spec_from_file_location("m4ml_scan_colmap_loader", ROOT / "scene/colmap_loader.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_sparse(model: Path):
    """Read cameras/images of a .bin or .txt model with the original loader."""
    reader = _loader()
    if (model / "images.bin").is_file():
        return reader.read_intrinsics_binary(str(model / "cameras.bin")), reader.read_extrinsics_binary(str(model / "images.bin"))
    return reader.read_intrinsics_text(str(model / "cameras.txt")), reader.read_extrinsics_text(str(model / "images.txt"))


def _points_count(model: Path):
    if (model / "points3D.bin").is_file():
        with (model / "points3D.bin").open("rb") as f:
            return struct.unpack("<Q", f.read(8))[0]
    with (model / "points3D.txt").open(errors="replace") as f:
        return sum(1 for line in f if line.strip() and not line.startswith("#"))


def analyse_sparse(model: Path, image_dirs: dict, root: Path):
    item = {"path": model.relative_to(root).as_posix() or ".", "format": "bin" if (model / "images.bin").is_file() else "txt", "valid": False}
    try:
        cameras, poses = read_sparse(model)
        names = [p.name for p in poses.values()]
        item.update(
            registered=len(poses),
            cameras=len(cameras),
            camera_models=sorted({c.model for c in cameras.values()}),
            points=_points_count(model),
            undistorted=all(c.model in {"PINHOLE", "SIMPLE_PINHOLE"} for c in cameras.values()),
        )
        if not poses or not np.all([np.isfinite(p.qvec).all() and np.isfinite(p.tvec).all() for p in poses.values()]):
            raise ValueError("카메라 자세 값이 비어 있거나 유효하지 않습니다.")
        # which photo folder holds these registered names?
        def size_match(d):
            ok = 0
            for pose in list(poses.values())[:6]:
                photo = d / pose.name
                cam = cameras[pose.camera_id]
                try:
                    ok += _image_size(photo) == (cam.width, cam.height)
                except Exception:
                    pass
            return ok

        # most registered names first; ties broken by photo size == camera size (undistorted copies)
        scored = [(sum(1 for n in names if n in set(files)), d) for d, files in image_dirs.items()]
        top = max((c for c, _ in scored), default=0)
        tied = [d for c, d in scored if c == top and c]
        best = (top, max(tied, key=size_match)) if tied else (0, None)
        item["images_dir"] = best[1].relative_to(root).as_posix() if best[1] else None
        item["images_found"] = best[0]
        if best[0] < len(names):
            item["missing_images"] = sorted(set(names) - set(image_dirs.get(best[1], [])))[:20]
        if best[0] < 2:
            raise ValueError("이 카메라 정합 결과에 해당하는 사진을 찾지 못했습니다.")
        # size consistency for undistorted models (camera size must equal photo size)
        if item["undistorted"]:
            bad = 0
            for pose in list(poses.values())[:12]:
                photo = best[1] / pose.name
                if photo.is_file():
                    cam = cameras[pose.camera_id]
                    if _image_size(photo) != (cam.width, cam.height):
                        bad += 1
            if bad:
                item["undistorted"] = False
                item["note"] = "카메라 크기와 사진 크기가 달라 왜곡 보정을 다시 실행합니다."
        item["valid"] = True
        item["_poses"] = poses
        item["_names"] = names
    except Exception as exc:  # report, never raise: a broken model must not hide the photos
        item["error"] = str(exc) if str(exc) else exc.__class__.__name__
    return item


# --------------------------------------------------------------------------- masks
def analyse_masks(mask_dirs: list, root: Path, names: list, photo_dir: Path | None):
    if not mask_dirs or not names:
        return None
    stems = {Path(n).stem.casefold(): n for n in names}
    best = None
    for d, files in mask_dirs:
        found = {Path(f).stem.casefold() for f in files if Path(f).suffix.lower() in IMAGE_EXT}
        matched = [stems[s] for s in found if s in stems]
        if not best or len(matched) > len(best[1]):
            best = (d, matched, files)
    d, matched, files = best
    report = {"dir": d.relative_to(root).as_posix(), "files": len(files), "matched": len(matched), "expected": len(names),
              "missing": sorted(set(names) - set(matched))[:30], "valid": False}
    # integrity sample: size equality and binary content
    problems = []
    from PIL import Image

    lookup = {Path(f).stem.casefold(): d / f for f in files}
    for name in sorted(matched)[:16]:
        path = lookup[Path(name).stem.casefold()]
        try:
            with Image.open(path) as m:
                size = m.size
                a = np.asarray(m.convert("L"))
            if photo_dir and (photo_dir / name).is_file() and _image_size(photo_dir / name) != size:
                problems.append(f"{path.name}: 사진과 크기가 다릅니다 {size}")
            values = np.unique(a)
            if len(values) > 2 and not np.isin(values, [0, 255]).all() and len(values) > 16:
                problems.append(f"{path.name}: 이진 마스크가 아닙니다")
            if not a.any():
                problems.append(f"{path.name}: 비어 있는 마스크입니다")
        except Exception as exc:
            problems.append(f"{path.name}: 읽을 수 없습니다 ({exc})")
    report["problems"] = problems[:10]
    report["complete"] = len(matched) == len(names) and not problems
    report["valid"] = bool(matched) and not problems
    return report


# --------------------------------------------------------------------------- training outputs
def _cfg_source(cfg: Path):
    if cfg.stat().st_size>16384:raise ValueError("학습 설정 파일이 너무 큽니다.")
    m = re.search(r"source_path='([^']*)'", cfg.read_text(errors="replace"))
    return m[1] if m else None


def _ply_header(path: Path):
    """Parse a PLY header without loading the body: element counts and vertex properties."""
    header = {"elements": {}, "vertex_props": []}
    with path.open("rb") as f:
        if f.readline().strip() != b"ply":
            raise ValueError("PLY 파일이 아닙니다.")
        current = None
        for _ in range(200):
            line = f.readline().decode("ascii", errors="replace").strip()
            if line.startswith("element"):
                _, current, count = line.split()[:3]
                header["elements"][current] = int(count)
            elif line.startswith("property") and current == "vertex":
                header["vertex_props"].append(line.split()[-1])
            elif line == "end_header":
                return header
    raise ValueError("PLY 헤더가 손상되었습니다.")


def analyse_training(model: Path, root: Path, poses: dict | None):
    item = {"path": model.relative_to(root).as_posix(), "valid": False}
    try:
        iters = sorted(
            int(p.name.split("_")[1])
            for p in (model / "point_cloud").glob("iteration_*")
            if (p / "point_cloud.ply").is_file() and p.name.split("_")[1].isdigit()
        )
        ckpts = sorted(
            int(m[1])
            for p in model.glob("chkpnt*.pth")
            if (m := re.fullmatch(r"chkpnt(\d+)\.pth", p.name))
        )
        item.update(
            iterations=iters,
            checkpoints=ckpts,
            source_path=_cfg_source(model / "cfg_args"),
        )
        if iters:
            from studio.result_artifacts import inspect_result

            result = inspect_result(
                model / "point_cloud" / f"iteration_{iters[-1]}" / "point_cloud.ply",
                root,
            )
            if not result["valid"] or result["kind"] != "gaussian":
                raise ValueError(
                    result.get("error", "Object-Aware Gaussian 형식이 아닙니다.")
                )
            item["gaussians"] = result["vertices"]
            item["has_objectmark"] = True
        for c in ckpts:
            with (model / f"chkpnt{c}.pth").open("rb") as f:
                if f.read(2) != b"PK":
                    raise ValueError(f"chkpnt{c}.pth 파일이 손상되었습니다.")
        if ckpts and not iters:
            item["resume_compatible"] = False
            item["note"] = (
                "저장 지점의 전체 실행 설정과 데이터 해시 검증 기록이 없어 안전한 재개를 확인할 수 없습니다. 새로 학습하세요."
            )
        # does this output belong to THIS dataset? names + camera centres
        cams = (
            json.loads((model / "cameras.json").read_text())
            if (model / "cameras.json").is_file()
            else None
        )
        item["dataset_match"] = "unknown"
        if cams and poses:
            from studio.colmap import loader

            reader = loader()
            by_stem = {Path(p.name).stem: p for p in poses.values()}
            matched = [c for c in cams if c["img_name"] in by_stem]
            item["cameras_matched"] = f"{len(matched)}/{len(cams)}"
            if len(matched) == len(cams) and matched:
                centers = np.array(
                    [
                        -(
                            reader.qvec2rotmat(by_stem[c["img_name"]].qvec).T
                            @ by_stem[c["img_name"]].tvec
                        )
                        for c in matched
                    ]
                )
                trained = np.array([c["position"] for c in matched])
                scale = max(
                    float(np.linalg.norm(centers - centers.mean(0), axis=1).mean()),
                    1e-9,
                )
                err = float(np.abs(centers - trained).max() / scale)
                item["camera_center_error"] = err
                item["dataset_match"] = "yes" if err < 1e-3 else "no"
            else:
                item["dataset_match"] = "no"
        elif cams is None:
            item["dataset_match"] = "unknown"
        item["valid"] = bool(iters or ckpts)
    except Exception as exc:
        item["error"] = str(exc)
    return item


def analyse_mesh(path: Path, root: Path):
    item = {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "valid": False}
    try:
        if path.suffix.lower() == ".glb":
            with path.open("rb") as f:
                if f.read(4) != b"glTF":
                    raise ValueError("GLB 헤더가 아닙니다.")
            item.update(kind="glb", valid=True, colors=None)
        else:
            h = _ply_header(path)
            faces = h["elements"].get("face", 0)
            if not faces:
                raise ValueError("면(face)이 없는 점 구름입니다.")
            item.update(kind="ply", vertices=h["elements"].get("vertex", 0), triangles=faces,
                        colors=all(c in h["vertex_props"] for c in ("red", "green", "blue")), valid=True)
    except Exception as exc:
        item["error"] = str(exc)
    return item


# --------------------------------------------------------------------------- top level
STAGE_LABEL = {
    "colmap": "카메라 정합",
    "sam": "객체 선택",
    "review": "마스크 검토",
    "train": "3D 재구성",
    "train_resume": "3D 재구성 (이어서)",
    "mesh": "3D 모델 생성",
    "view": "3D 모델 보기",
}


def scan_folder(folder) -> dict:
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("폴더를 찾을 수 없습니다.")
    tree = _walk(root)
    image_dirs = {
        d: sorted(f for f in files if Path(f).suffix.lower() in IMAGE_EXT)
        for d, files in tree.items()
        if not _is_mask_dir(d, root) and not _in_training_output(d, root)
    }
    image_dirs = {d: f for d, f in image_dirs.items() if len(f) >= 2}
    mask_dirs = [
        (d, files) for d, files in tree.items() if _is_mask_dir(d, root) and files
    ]

    # M4ML Studio project metadata
    manifest = None
    if (root / "manifest.json").is_file():
        try:
            m = json.loads((root / "manifest.json").read_text())
            if "stages" in m and "schema_version" in m:
                manifest = {
                    "id": m.get("id"),
                    "name": m.get("name"),
                    "stages": m.get("stages"),
                }
        except ValueError:
            pass

    sparse = [
        analyse_sparse(d, image_dirs, root)
        for d, files in tree.items()
        if (
            {"cameras.bin", "images.bin", "points3D.bin"} <= set(files)
            or {"cameras.txt", "images.txt", "points3D.txt"} <= set(files)
        )
    ]
    valid_sparse = sorted(
        (s for s in sparse if s["valid"]),
        key=lambda s: (s["undistorted"], s["registered"]),
        reverse=True,
    )
    selected = valid_sparse[0] if valid_sparse else None

    photos_dir = None
    if selected and selected.get("images_dir") is not None:
        photos_dir = root / selected["images_dir"]
    elif image_dirs:
        preferred = [
            d
            for d in image_dirs
            if d.name.lower() in {"images", "input", "photos", "imgs"}
        ]
        photos_dir = max(preferred or image_dirs, key=lambda d: len(image_dirs[d]))
    photos = image_dirs.get(photos_dir, []) if photos_dir else []
    images = None
    if photos:
        sizes = {}
        for f in photos[:6]:
            try:
                sizes[f] = list(_image_size(photos_dir / f))
            except Exception:
                pass
        images = {
            "dir": photos_dir.relative_to(root).as_posix() or ".",
            "count": len(photos),
            "sample_sizes": sizes,
            "bytes": sum((photos_dir / f).stat().st_size for f in photos),
        }

    names = selected["_names"] if selected else []
    masks = analyse_masks(mask_dirs, root, names, photos_dir) if selected else None

    trainings = [
        analyse_training(d, root, selected["_poses"] if selected else None)
        for d, files in tree.items()
        if "cfg_args" in files
        and ((d / "point_cloud").is_dir() or any(f.startswith("chkpnt") for f in files))
    ]
    from studio.result_artifacts import inspect_result, MAX_ARTIFACTS

    candidates = [
        d / f
        for d, files in tree.items()
        for f in sorted(files)
        if Path(f).suffix.lower() in {".ply", ".glb", ".obj"}
    ]
    artifacts = [inspect_result(path, root) for path in candidates[:MAX_ARTIFACTS]]
    artifacts.sort(key=lambda m: (m["valid"], m.get("modified", 0)), reverse=True)
    meshes = [
        {**m, "kind": m.get("format", "ply")} for m in artifacts if m["kind"] == "mesh"
    ]

    for s in sparse:
        s.pop("_poses", None), s.pop("_names", None)

    # ------------------------------------------------------------------ recommendation
    problems, reasons = [], []
    usable_training = [
        t for t in trainings if t["valid"] and t.get("dataset_match") == "yes"
    ]
    finished = [t for t in usable_training if t.get("iterations")]
    resumable = [
        t
        for t in usable_training
        if t.get("checkpoints")
        and not t.get("iterations")
        and t.get("resume_compatible")
    ]
    # A mesh inside a training output belongs to that output's dataset: usable only with it.
    rejected = [t["path"] for t in trainings if t not in usable_training]
    for m in meshes:
        if m["valid"] and any(m["path"].startswith(r + "/") for r in rejected):
            m["usable"] = False
            m["note"] = "사용하지 않는 학습 결과 안의 모델"
        else:
            m["usable"] = m["valid"]
    good_mesh = next((m for m in meshes if m["usable"]), None)
    trained_mesh = next(
        (
            m
            for m in meshes
            if m["usable"]
            and finished
            and m["path"].startswith(finished[0]["path"] + "/")
        ),
        None,
    )
    for t in trainings:
        if t["valid"] and t.get("dataset_match") != "yes":
            problems.append(
                f"학습 결과 {t['path']}는 이 폴더의 카메라 정합 결과와 일치하지 않아 사용하지 않습니다."
            )
    for s in sparse:
        if not s["valid"]:
            problems.append(
                f"카메라 정합 결과 {s['path']}를 사용할 수 없습니다: {s.get('error')}"
            )
    if masks and masks["problems"]:
        problems.extend(masks["problems"][:3])

    good_result = next((a for a in artifacts if a["valid"]), None)
    if not images and not selected and not good_mesh and not good_result:
        stage = None
        problems.insert(
            0,
            "사진, 카메라 정합 결과, 3D 모델을 찾지 못했습니다. 프로젝트 데이터가 있는 폴더를 선택하세요.",
        )
    elif selected and finished:
        stage = "view" if trained_mesh else "mesh"
        reasons.append(
            "이 데이터셋으로 학습된 결과가 있습니다."
            + ("" if trained_mesh else " 3D 모델을 학습 결과에서 새로 만듭니다.")
        )
    elif selected and resumable:
        stage = "train_resume"
        reasons.append(
            f"학습 저장 지점 {resumable[0]['checkpoints'][-1]:,}회가 있어 이어서 학습할 수 있습니다."
        )
    elif selected and masks and masks["complete"]:
        stage = "train"
        reasons.append("등록된 모든 사진에 유효한 마스크가 있습니다.")
    elif selected and masks and masks["valid"]:
        stage = "review"
        reasons.append(
            f"마스크 {masks['matched']}/{masks['expected']}장이 있습니다. 나머지는 객체 선택으로 만듭니다."
        )
    elif selected:
        stage = "sam"
        reasons.append(f"카메라 {selected['registered']}장이 등록되어 있습니다.")
    elif (good_mesh or good_result) and not images:
        stage = "view"
        reasons.append("완성된 3D 모델 파일이 있습니다.")
    else:
        stage = "colmap"
        reasons.append(f"사진 {images['count']}장으로 카메라 정합부터 시작합니다.")
    if good_mesh and stage not in ("view",) and not (selected and finished):
        reasons.append(f"3D 모델 파일({good_mesh['path']})도 함께 열 수 있습니다.")

    if good_result:
        reasons.append(
            "기존 3D 결과는 데이터셋 연결을 가정하지 않고 독립적으로 열 수 있습니다."
        )
    return {
        "path": str(root),
        "name": root.name,
        "manifest": manifest,
        "images": images,
        "image_dirs": [
            {"dir": d.relative_to(root).as_posix() or ".", "count": len(f)}
            for d, f in sorted(image_dirs.items(), key=lambda t: -len(t[1]))
        ][:10],
        "sparse": sparse,
        "selected_sparse": selected["path"] if selected else None,
        "camera": (
            {
                k: selected[k]
                for k in (
                    "registered",
                    "cameras",
                    "camera_models",
                    "undistorted",
                    "points",
                    "images_found",
                )
                if k in selected
            }
            if selected
            else None
        ),
        "masks": masks,
        "training": trainings,
        "meshes": meshes[:64],
        "artifacts": artifacts,
        "artifact_scan_limited": len(candidates) > MAX_ARTIFACTS,
        "recommendation": {
            "stage": stage,
            "label": STAGE_LABEL.get(stage),
            "reasons": reasons,
        },
        "problems": problems,
    }
