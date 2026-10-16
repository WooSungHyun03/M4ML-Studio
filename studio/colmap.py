"""Real COLMAP CPU SfM and selected registered/undistorted scene auditing."""

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import shutil
import sqlite3

import numpy as np
from PIL import Image

from studio.doctor import ROOT, atomic_json
from studio.process import run


def loader():
    # Use the unchanged upstream binary readers without importing CUDA Scene.
    spec = importlib.util.spec_from_file_location(
        "studio_colmap_reader", ROOT / "scene/colmap_loader.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_model(directory):
    reader = loader()
    directory = Path(directory)
    return (
        reader.read_intrinsics_binary(str(directory / "cameras.bin")),
        reader.read_extrinsics_binary(str(directory / "images.bin")),
    )


def database_report(database, selected_names, components):
    with sqlite3.connect(f"file:{Path(database).resolve()}?mode=ro", uri=True) as db:
        features = dict(db.execute("SELECT image_id, rows FROM keypoints"))
        matched = set()
        pair_count = 0
        for pair, rows in db.execute("SELECT pair_id, rows FROM two_view_geometries"):
            if rows:
                matched.update((pair // 2147483647, pair % 2147483647))
                pair_count += 1
        images = []
        for image_id, name in db.execute(
            "SELECT image_id,name FROM images ORDER BY image_id"
        ):
            registered = name in selected_names
            other = [
                key
                for key, names in components.items()
                if name in names and not registered
            ]
            reason = (
                "등록 성공"
                if registered
                else (
                    "다른 재구성 그룹"
                    if other
                    else (
                        "매칭되었으나 카메라 등록 실패"
                        if image_id in matched
                        else "미매칭"
                    )
                )
            )
            images.append(
                {
                    "name": name,
                    "features_extracted": features.get(image_id, 0) > 0,
                    "feature_count": features.get(image_id, 0),
                    "has_verified_match": image_id in matched,
                    "registered": registered,
                    "other_components": other,
                    "reason": reason,
                }
            )
    return {
        "images": images,
        "verified_pairs": pair_count,
        "registered": len(selected_names),
        "total": len(images),
        "matched": sum(i["has_verified_match"] for i in images),
    }


def validate_scene(scene):
    scene = Path(scene)
    cameras, images = read_model(scene / "sparse/0")
    xyz, _, _ = loader().read_points3D_binary(str(scene / "sparse/0/points3D.bin"))
    if len(xyz) < 4 or not np.isfinite(xyz).all():
        raise ValueError(
            "유효한 3차원 특징점이 부족합니다. 충분히 겹치는 다른 시점의 사진으로 다시 재구성하세요."
        )
    if len(images) < 2:
        raise ValueError(
            "등록된 사진이 2장 이상 필요합니다. 촬영 범위와 겹침을 확인하세요."
        )
    names = set()
    stems = set()
    for pose in images.values():
        if Path(pose.name).name != pose.name or Path(pose.name).stem in stems:
            raise ValueError("등록 사진 이름이 안전하지 않거나 중복되었습니다.")
        camera = cameras[pose.camera_id]
        if camera.model not in {"PINHOLE", "SIMPLE_PINHOLE"}:
            raise ValueError(f"왜곡 보정되지 않은 카메라입니다: {camera.model}")
        if (
            not np.isfinite(camera.params).all()
            or not np.isfinite(pose.qvec).all()
            or not np.isfinite(pose.tvec).all()
        ):
            raise ValueError("카메라 보정 값이 유효하지 않습니다.")
        if np.any(camera.params[: 1 if camera.model == "SIMPLE_PINHOLE" else 2] <= 0):
            raise ValueError("카메라 초점 거리가 유효하지 않습니다.")
        if abs(np.linalg.norm(pose.qvec) - 1) > 0.001:
            raise ValueError("카메라 회전 값이 유효하지 않습니다.")
        with Image.open(scene / "images" / pose.name) as image:
            image.load()
            if image.size != (camera.width, camera.height):
                raise ValueError(f"사진과 카메라 크기가 다릅니다: {pose.name}")
        names.add(pose.name)
        stems.add(Path(pose.name).stem)
    if {p.name for p in (scene / "images").iterdir()} != names:
        raise ValueError("장면에 등록되지 않은 사진이 포함되어 있습니다.")
    return names


def reconstruct(
    image_dir,
    work,
    *,
    component=None,
    matching="exhaustive",
    cancel=None,
    progress=None,
):
    image_dir, work = Path(image_dir).resolve(), Path(work).resolve()
    if matching not in {"exhaustive", "sequential"}:
        raise ValueError("지원하지 않는 매칭 방식입니다.")
    work.mkdir(parents=True, exist_ok=False)
    sparse = work / "sparse"
    sparse.mkdir()
    database = work / "database.db"
    log = work / "colmap.log"

    def lines(line):
        import re

        found = re.search(r"Processed file \[(\d+)/(\d+)\]", line)
        if progress and found:
            progress(f"특징점 추출 {found[1]}/{found[2]}장")

    options = dict(cancel=cancel, on_line=lines, timeout=7200)
    if progress:
        progress("사진의 특징점을 추출하고 있습니다.")
    run(
        [
            "colmap",
            "feature_extractor",
            "--database_path",
            database,
            "--image_path",
            image_dir,
            "--SiftExtraction.use_gpu",
            "0",
            "--SiftExtraction.num_threads",
            "4",
        ],
        log,
        **options,
    )
    if progress:
        progress("사진 쌍의 특징점을 매칭하고 기하 관계를 검증하고 있습니다.")
    run(
        [
            "colmap",
            f"{matching}_matcher",
            "--database_path",
            database,
            "--SiftMatching.use_gpu",
            "0",
            "--SiftMatching.num_threads",
            "4",
        ],
        log,
        **options,
    )
    if progress:
        progress("카메라 위치를 등록하고 재구성 그룹을 찾고 있습니다.")
    run(
        [
            "colmap",
            "mapper",
            "--database_path",
            database,
            "--image_path",
            image_dir,
            "--output_path",
            sparse,
            "--Mapper.num_threads",
            "4",
        ],
        log,
        **options,
    )
    components = {}
    for model in sorted(sparse.iterdir()):
        if model.is_dir() and (model / "images.bin").is_file():
            _, images = read_model(model)
            components[model.name] = {pose.name for pose in images.values()}
    if not components:
        atomic_json(work / "report.json", database_report(database, set(), {}))
        raise ValueError(
            "카메라가 등록되지 않았습니다. 충분히 겹치는 사진을 추가하세요."
        )
    selected = component or max(components, key=lambda key: len(components[key]))
    if selected not in components or len(components[selected]) < 2:
        raise ValueError("선택한 재구성 그룹의 등록 사진이 부족합니다.")
    report = database_report(database, components[selected], components)
    report.update(
        {
            "selected_component": selected,
            "components": {k: sorted(v) for k, v in components.items()},
        }
    )
    atomic_json(work / "report.json", report)
    scene = work / "scene"
    if progress:
        progress("선택한 등록 사진의 렌즈 왜곡을 보정하고 있습니다.")
    run(
        [
            "colmap",
            "image_undistorter",
            "--image_path",
            image_dir,
            "--input_path",
            sparse / selected,
            "--output_path",
            scene,
            "--output_type",
            "COLMAP",
        ],
        log,
        **options,
    )
    target = scene / "sparse/0"
    target.mkdir()
    for name in ("cameras.bin", "images.bin", "points3D.bin"):
        shutil.move(scene / "sparse" / name, target / name)
    # The undistorter normally exports only registered photos; never silently
    # accept extra files or a calibration/image mismatch.
    names = validate_scene(scene)
    report = database_report(database, names, components)
    report.update(
        {
            "selected_component": selected,
            "components": {key: sorted(value) for key, value in components.items()},
        }
    )
    atomic_json(work / "report.json", report)
    return report


def select_existing(image_dir, previous, work, component, cancel=None):
    previous, work = Path(previous), Path(work)
    old = json_load(previous / "report.json")
    if component not in old["components"] or len(old["components"][component]) < 2:
        raise ValueError("유효한 재구성 그룹을 선택하세요.")
    work.mkdir(parents=True, exist_ok=False)
    shutil.copytree(previous / "sparse", work / "sparse")
    shutil.copyfile(previous / "database.db", work / "database.db")
    scene = work / "scene"
    run(
        [
            "colmap",
            "image_undistorter",
            "--image_path",
            image_dir,
            "--input_path",
            work / "sparse" / component,
            "--output_path",
            scene,
            "--output_type",
            "COLMAP",
        ],
        work / "colmap.log",
        cancel=cancel,
    )
    (scene / "sparse/0").mkdir()
    for name in ("cameras.bin", "images.bin", "points3D.bin"):
        shutil.move(scene / "sparse" / name, scene / "sparse/0" / name)
    names = validate_scene(scene)
    report = database_report(
        work / "database.db", names, {k: set(v) for k, v in old["components"].items()}
    )
    report.update(selected_component=component, components=old["components"])
    atomic_json(work / "report.json", report)
    return report


def json_load(path):
    import json

    return json.loads(Path(path).read_text())


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("images", type=Path)
    p.add_argument("work", type=Path)
    args = p.parse_args()
    print(reconstruct(args.images, args.work))
