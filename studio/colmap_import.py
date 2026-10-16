"""Import browser-authorized COLMAP outputs; never invent/re-estimate poses."""

from pathlib import Path
import json, shutil, struct, uuid
from io import BytesIO
import numpy as np
from PIL import Image
from studio.colmap import loader, read_model, validate_scene


def camera_binary():
    """The configured camera-reconstruction engine binary (bundled build preferred)."""
    from studio.engines import provider

    path, _probe, _origin = provider("camera").binary()
    return str(path)
from studio.doctor import atomic_json, sha256
from studio.importer import atomic_bytes, import_image, MAX_PIXELS
from studio.process import run
from studio.sam31 import validate_mask

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def safe(root, relative):
    p = (Path(root) / relative).resolve()
    base = Path(root).resolve()
    if p != base and base not in p.parents:
        raise ValueError("가져오기 폴더 밖의 경로는 사용할 수 없습니다.")
    return p


def candidates(root):
    root = Path(root)
    found = []
    for p in root.rglob("cameras.*"):
        if (
            p.suffix in {".bin", ".txt"}
            and (p.parent / ("images" + p.suffix)).is_file()
            and (p.parent / ("points3D" + p.suffix)).is_file()
        ):
            found.append(p.parent.relative_to(root).as_posix())
    return sorted(set(found))


def binary_model(source, output, log):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # Even binary input passes the official parser/converter in an isolated copy.
    for stem in ("cameras", "images", "points3D"):
        f = source / (stem + ".bin")
        if f.exists():
            if f.stat().st_size < 8 or f.stat().st_size > 512 * 1024**2:
                raise ValueError(f"{f.name}: 모델 파일 크기가 유효하지 않습니다.")
            with f.open("rb") as stream:
                count = struct.unpack("<Q", stream.read(8))[0]
            if count > 10_000_000:
                raise ValueError(f"{f.name}: 모델 항목 수가 너무 큽니다.")
    run(
        [
            camera_binary(),
            "model_converter",
            "--input_path",
            str(source),
            "--output_path",
            str(output),
            "--output_type",
            "BIN",
        ],
        log,
        timeout=120,
    )
    return read_model(output)


def image_folder(root, poses, override=None):
    if override:
        return safe(root, override)
    trials = []
    for name in ("images", "input"):
        trials.extend(p for p in Path(root).rglob(name) if p.is_dir())
    trials.append(Path(root))
    scores = [(sum((p / i.name).is_file() for i in poses.values()), p) for p in trials]
    return max(scores, key=lambda t: t[0])[1]


def mask_folder(root, override=None):
    if override:
        return safe(root, override)
    for name in ("mask", "masks"):
        for p in Path(root).rglob(name):
            if p.is_dir():
                return p
    return None


def mask_file(directory, name):
    if directory is None:
        return None
    direct = directory / (str(Path(name).with_suffix(".png")))
    if direct.is_file():
        return direct
    stem = Path(name).stem.casefold()
    hits = [
        p
        for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXT and p.stem.casefold() == stem
    ]
    if len(hits) > 1:
        raise ValueError(
            f"{name}: 대응 마스크가 여러 개입니다. 폴더를 다시 매핑하세요."
        )
    return hits[0] if hits else None


def mask_data(path, size, options):
    if path is None:
        raise ValueError("대응 마스크가 없습니다. mask 폴더와 사진 stem을 확인하세요.")
    with Image.open(path) as image:
        image.load()
        if image.size != tuple(size):
            raise ValueError(
                f"{path.name}: 마스크 크기{image.size}가 사진{tuple(size)}과 다릅니다."
            )
        a = np.asarray(image)
        if options.get("mask_channel") == "alpha":
            if image.mode != "RGBA":
                raise ValueError(f"{path.name}: 알파 채널이 없습니다.")
            a = a[:, :, 3]
        elif a.ndim == 3:
            if not np.array_equal(a[:, :, 0], a[:, :, 1]) or not np.array_equal(
                a[:, :, 1], a[:, :, 2]
            ):
                raise ValueError(
                    f"{path.name}: 흑백 마스크 또는 알파 채널을 선택하세요."
                )
            a = a[:, :, 0]
        if image.mode not in ("L",) or not np.isin(a, [0, 255]).all():
            if not options.get("normalize_masks"):
                raise ValueError(
                    f"{path.name}: 단일 채널0/255가 아닙니다. 명시적 정규화를 선택하세요."
                )
            a = (a > 127 if a.dtype != bool else a).astype(np.uint8) * 255
        if options.get("foreground") == "black":
            a = 255 - a
        if not np.any(a):
            raise ValueError(
                f"{path.name}: 대상 마스크가 비어 있습니다. 전경 색을 확인하세요."
            )
        stream = BytesIO()
        Image.fromarray(a.astype(np.uint8), "L").save(stream, format="PNG")
        return stream.getvalue()


def inspect_colmap_import(root, options, work):
    root = Path(root).resolve()
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    choices = candidates(root)
    audit = {
        "components": [],
        "blocking_errors": [],
        "warnings": [],
        "images": [],
        "repairs": [],
        "stage_source": "imported",
    }
    if not choices:
        audit["blocking_errors"].append(
            "cameras/images/points3D의 bin 또는 txt 모델을 찾지 못했습니다."
        )
        return audit
    models = {}
    for n, rel in enumerate(choices):
        try:
            camera, poses = binary_model(
                safe(root, rel), work / f"model-{n}", work / "inspect.log"
            )
            models[rel] = (camera, poses, work / f"model-{n}")
            audit["components"].append({"path": rel, "registered": len(poses)})
        except Exception as e:
            audit["components"].append({"path": rel, "error": str(e)})
    if not models:
        audit["blocking_errors"].append(
            "읽을 수 있는 카메라 정합 결과(COLMAP 형식 sparse 모델)가 없습니다. 폴더와 모델 파일을 확인하세요."
        )
        return audit
    selected = options.get("sparse") or max(models, key=lambda k: len(models[k][1]))
    if selected not in models:
        audit["blocking_errors"].append(
            f"{selected}: 선택한 sparse 모델을 읽을 수 없습니다."
        )
        return audit
    cameras, poses, model = models[selected]
    folder = image_folder(root, poses, options.get("images"))
    masks = mask_folder(root, options.get("masks"))
    audit.update(
        selected_sparse=selected,
        paths={
            "images": folder.relative_to(root).as_posix(),
            "masks": masks.relative_to(root).as_posix() if masks else None,
        },
        camera_models=sorted({c.model for c in cameras.values()}),
        undistortion_state=(
            "required"
            if any(
                c.model not in {"PINHOLE", "SIMPLE_PINHOLE"} for c in cameras.values()
            )
            else "verified_pinhole"
        ),
    )
    if len(models) > 1:
        audit["warnings"].append("여러 좌표계가 있습니다. 선택한 한 그룹만 사용합니다.")
    names = set()
    ids = set()
    for pose in poses.values():
        row = {"name": pose.name, "registered": True, "valid": True}
        try:
            if pose.id in ids or pose.name in names:
                raise ValueError("중복 이미지 ID 또는 이름입니다.")
            names.add(pose.name)
            ids.add(pose.id)
            photo = safe(folder, pose.name)
            camera = cameras[pose.camera_id]
            if (
                not np.isfinite(pose.qvec).all()
                or not np.isfinite(pose.tvec).all()
                or abs(np.linalg.norm(pose.qvec) - 1) > 0.001
                or not np.isfinite(camera.params).all()
                or camera.params[0] <= 0
            ):
                raise ValueError("카메라 포즈/내부 보정 값이 유효하지 않습니다.")
            with Image.open(photo) as image:
                image.load()
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError("사진이5천만 화소를 초과합니다.")
                if image.getexif().get(274, 1) != 1:
                    raise ValueError(
                        "EXIF 방향이 카메라 정합 결과와 맞지 않습니다. 카메라 정합에 사용한 방향의 사진을 선택하세요."
                    )
                if image.size != (camera.width, camera.height):
                    raise ValueError(
                        f"사진 크기{image.size}와 카메라{camera.width,camera.height}가 다릅니다."
                    )
                row["size"] = list(image.size)
            if options.get("with_masks"):
                mp = mask_file(masks, pose.name)
                mask_data(mp, row["size"], options)
                row["mask"] = mp.relative_to(root).as_posix()
        except Exception as e:
            row.update(valid=False, error=f"{pose.name}: {e}")
            if "size" not in row:
                audit["blocking_errors"].append(row["error"])
            elif options.get("with_masks"):
                row["mask_error"] = row["error"]
        audit["images"].append(row)
    audit["registered"] = len(poses)
    audit["mask_errors"] = [i for i in audit["images"] if i.get("mask_error")]
    if len(poses) < 2:
        audit["blocking_errors"].append("등록 사진이2장 이상 필요합니다.")
    xyz, _, _ = loader().read_points3D_binary(str(model / "points3D.bin"))
    if len(xyz) < 4 or not np.isfinite(xyz).all():
        audit["blocking_errors"].append("유효한3차원 특징점이 부족합니다.")
    if audit["undistortion_state"] == "required" and options.get("with_masks"):
        unsupported = [
            c.model
            for c in cameras.values()
            if c.model
            not in {"PINHOLE", "SIMPLE_PINHOLE", "SIMPLE_RADIAL", "RADIAL", "OPENCV"}
        ]
        if unsupported:
            audit["blocking_errors"].append(
                "이 카메라의 마스크 좌표 변환은 지원하지 않습니다: "
                + ", ".join(unsupported)
                + ". 왜곡 보정된 사진과 마스크를 가져오세요."
            )
    all_images = [
        p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXT
    ]
    audit["excluded"] = [
        str(p.relative_to(folder))
        for p in all_images
        if str(p.relative_to(folder)) not in names
    ]
    atomic_json(work / "audit.json", audit)
    return audit


def write_model(cameras, poses, directory, mapping):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    reader = loader()
    data = bytearray(struct.pack("<Q", len(cameras)))
    for c in cameras.values():
        data.extend(
            struct.pack(
                "<iiQQ",
                c.id,
                reader.CAMERA_MODEL_NAMES[c.model].model_id,
                c.width,
                c.height,
            )
            + np.asarray(c.params, dtype="<f8").tobytes()
        )
    atomic_bytes(directory / "cameras.bin", data)
    data = bytearray(struct.pack("<Q", len(poses)))
    for i in poses.values():
        data.extend(
            struct.pack("<i", i.id)
            + np.asarray(i.qvec, dtype="<f8").tobytes()
            + np.asarray(i.tvec, dtype="<f8").tobytes()
            + struct.pack("<i", i.camera_id)
            + mapping[i.name].encode()
            + b"\0"
            + struct.pack("<Q", len(i.xys))
        )
        tracks = np.empty(len(i.xys), dtype=[("x", "<f8"), ("y", "<f8"), ("id", "<i8")])
        if len(i.xys):
            tracks["x"] = i.xys[:, 0]
            tracks["y"] = i.xys[:, 1]
            tracks["id"] = i.point3D_ids
        data.extend(tracks.tobytes())
    atomic_bytes(directory / "images.bin", data)


def warp_mask(a, old, new):
    import cv2

    if old.model == "SIMPLE_PINHOLE":
        f, cx, cy = old.params
        fx = fy = f
        dist = np.zeros(5)
    elif old.model == "PINHOLE":
        fx, fy, cx, cy = old.params
        dist = np.zeros(5)
    elif old.model in {"SIMPLE_RADIAL", "RADIAL"}:
        f, cx, cy, *k = old.params
        fx = fy = f
        dist = np.array([k[0], k[1] if len(k) > 1 else 0, 0, 0, 0])
    elif old.model == "OPENCV":
        fx, fy, cx, cy, k1, k2, p1, p2 = old.params
        dist = np.array([k1, k2, p1, p2, 0])
    else:
        raise ValueError("지원하지 않는 마스크 왜곡 보정 카메라입니다.")
    if new.model == "PINHOLE":
        nx, ny, px, py = new.params
    else:
        nx, px, py = new.params
        ny = nx
    original = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], float)
    target = np.array([[nx, 0, px], [0, ny, py], [0, 0, 1]], float)
    x, y = cv2.initUndistortRectifyMap(
        original, dist, None, target, (new.width, new.height), cv2.CV_32FC1
    )
    return cv2.remap(a, x, y, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT)


def commit_import(project_root, options, source=None):
    """Copy a verified external calibration (+masks) into the project.

    ``source`` defaults to the browser upload area; the desktop "open folder" flow passes the
    user's folder directly. The source is only read; everything is written under the project."""
    root = Path(project_root).resolve()
    uploaded = Path(source).resolve() if source else root / "import-upload"
    run_dir = root / "imports" / str(uuid.uuid4())
    run_dir.mkdir(parents=True)
    audit = inspect_colmap_import(uploaded, options, run_dir / "inspection")
    if audit["blocking_errors"] or audit["mask_errors"]:
        return {"audit": audit, "committed": False}
    source = safe(uploaded, audit["selected_sparse"])
    cameras, poses = binary_model(
        source, run_dir / "source-model", run_dir / "import.log"
    )
    photos = safe(uploaded, audit["paths"]["images"])
    maskdir = mask_folder(uploaded, options.get("masks"))
    model = run_dir / "source-model"
    transformed = False
    if audit["undistortion_state"] == "required":
        run(
            [
                camera_binary(),
                "image_undistorter",
                "--image_path",
                str(photos),
                "--input_path",
                str(model),
                "--output_path",
                str(run_dir / "undistorted"),
                "--output_type",
                "COLMAP",
                "--max_image_size",
                "100000",
            ],
            run_dir / "import.log",
            timeout=3600,
        )
        photos = run_dir / "undistorted/images"
        model = run_dir / "undistorted/sparse"
        transformed = True
    new_cameras, new_poses = read_model(model)
    scene = run_dir / "scene"
    (scene / "images").mkdir(parents=True)
    mapping = {
        old.name: f"{n:06d}.png"
        for n, old in enumerate(sorted(new_poses.values(), key=lambda p: p.id), 1)
    }
    images = []
    masks = {}
    for old in sorted(poses.values(), key=lambda p: p.id):
        name = mapping[old.name]
        photo = photos / old.name
        # Canonical immutable image/snapshot importer, but no duplicate removal from a calibrated component.
        item = import_image(root, photo.read_bytes(), old.name, len(images) + 1, [])
        item["imported_source"] = old.name
        images.append(item)
        shutil.copyfile(root / item["path"], scene / "images" / name)
        if options.get("with_masks"):
            raw = mask_data(
                mask_file(maskdir, old.name),
                (cameras[old.camera_id].width, cameras[old.camera_id].height),
                options,
            )
            if transformed:
                a = np.asarray(Image.open(BytesIO(raw)))
                a = warp_mask(
                    a, cameras[old.camera_id], new_cameras[new_poses[old.id].camera_id]
                )
                encoded = BytesIO()
                Image.fromarray(a).save(encoded, format="PNG")
                raw = encoded.getvalue()
            target = run_dir / "masks" / name
            atomic_bytes(target, raw)
            with Image.open(scene / "images" / name) as image:
                stats = validate_mask(target, image.size)
            masks[name] = {
                **stats,
                "valid": True,
                "status": "imported",
                "source": "imported",
                "path": str(target.relative_to(root)),
                "generated_path": str(target.relative_to(root)),
                "source_name": old.name,
                "warnings": ["가져온 마스크 · 검토 전"],
            }
    write_model(new_cameras, new_poses, scene / "sparse/0", mapping)
    shutil.copyfile(model / "points3D.bin", scene / "sparse/0/points3D.bin")
    validate_scene(scene)
    report = {
        "registered": len(images),
        "total": len(images) + len(audit["excluded"]),
        "matched": None,
        "verified_pairs": None,
        "selected_component": audit["selected_sparse"],
        "components": {audit["selected_sparse"]: list(mapping.values())},
        "images": [
            {
                "name": i["name"],
                "registered": True,
                "features_extracted": None,
                "feature_count": 0,
                "has_verified_match": None,
                "reason": "가져온 등록 카메라",
            }
            for i in images
        ]
        + [
            {
                "name": n,
                "registered": False,
                "feature_count": 0,
                "has_verified_match": None,
                "reason": "미등록 · 가져오기 제외",
            }
            for n in audit["excluded"]
        ],
    }
    provenance = {
        "stage_source": "imported",
        "stage_state": "verified",
        "skip_reason": "existing_valid_output",
        "paths": audit["paths"],
        "selected_sparse": audit["selected_sparse"],
        "name_mapping": mapping,
        "undistorted_during_import": transformed,
        "options": options,
    }
    return {
        "committed": True,
        "audit": audit,
        "scene": str(scene.relative_to(root)),
        "images": images,
        "masks": masks,
        "colmap_report": report,
        "provenance": provenance,
    }
