"""Bounded, read-only result classification. Native 2DGS is never inferred from an extension."""

from pathlib import Path
import numpy as np

MAX_BYTES = 1024**3
MAX_VERTICES = 5_000_000
MAX_FACES = 10_000_000
MAX_ARTIFACTS = 64
# These are log-scales: exp(-67) is tiny, not an enormous primitive. Application
# input limits (not a different PLY schema); preserve the observed native range.
LOG_SCALE_MIN, LOG_SCALE_MAX = -80.0, 30.0


def inspect_result(path, root=None):
    path = Path(path).absolute()
    root = Path(root or path.parent).resolve()
    item = {
        "path": path.relative_to(root).as_posix(),
        "kind": "invalid",
        "valid": False,
        "usable": False,
    }
    try:
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError("외부 경로 또는 심볼릭 링크는 가져오지 않습니다.")
        stat = path.stat()
        item.update(bytes=stat.st_size, modified=stat.st_mtime)
        if stat.st_size > MAX_BYTES:
            raise ValueError("결과 파일은 1GB 이하만 지원합니다.")
        if path.suffix.lower() == ".glb":
            from studio.mesh import check_glb_resources

            check_glb_resources(path, vertex_colors_only=True)
            import trimesh

            mesh = trimesh.load(path, force="mesh", process=False)
            if (
                not len(mesh.vertices)
                or not len(mesh.faces)
                or not np.isfinite(mesh.vertices).all()
            ):
                raise ValueError("유효한 면과 정점이 필요합니다.")
            if len(mesh.vertices) > MAX_VERTICES or len(mesh.faces) > MAX_FACES:
                raise ValueError("모델 크기 제한을 초과했습니다.")
            item.update(
                kind="mesh",
                format="glb",
                vertices=len(mesh.vertices),
                triangles=len(mesh.faces),
                colors=None,
                valid=True,
                usable=True,
            )
            return item
        if path.suffix.lower() != ".ply":
            item.update(
                kind="unsupported", error="현재 직접 가져오기는 PLY·GLB를 지원합니다."
            )
            return item
        # Guard counts, types, variable lists and header allocation BEFORE reading the payload.
        elements = {}
        props = []
        current = None
        header_bytes = 0
        fmt = None
        with path.open("rb") as f:
            if f.readline() != b"ply\n":
                f.seek(0)
                if f.readline().strip() != b"ply":
                    raise ValueError("PLY 헤더가 아닙니다.")
            for _ in range(4096):
                line = f.readline(4097)
                header_bytes += len(line)
                if len(line) > 4096 or header_bytes > 262144 or not line:
                    raise ValueError("PLY 헤더가 손상되었거나 너무 큽니다.")
                words = line.decode("ascii").strip().split()
                if words[:1] == ["format"]:
                    fmt = words[1]
                if words[:1] == ["element"]:
                    current = words[1]
                    n = int(words[2])
                    elements[current] = n
                    if (
                        n < 0
                        or current not in ("vertex", "face")
                        or n > (MAX_VERTICES if current == "vertex" else MAX_FACES)
                    ):
                        raise ValueError("PLY 요소 또는 크기를 지원하지 않습니다.")
                if words[:1] == ["property"] and current == "vertex":
                    if words[1] == "list":
                        raise ValueError("가변 길이 정점 속성은 지원하지 않습니다.")
                    props.append(words[-1])
                if words == ["end_header"]:
                    break
            else:
                raise ValueError("PLY 헤더가 끝나지 않았습니다.")
        if not elements.get("vertex") or len(props) != len(set(props)):
            raise ValueError("정점이 없거나 속성이 중복되었습니다.")
        if fmt == "ascii" and stat.st_size > 64 * 1024**2:
            raise ValueError("대용량 ASCII PLY는 binary PLY로 내보내세요 (64MB 제한).")
        if fmt not in ("ascii", "binary_little_endian", "binary_big_endian"):
            raise ValueError("지원하지 않는 PLY 인코딩입니다.")
        # Minimum payload size check blocks huge forged element counts before plyfile allocation.
        if stat.st_size - header_bytes < elements["vertex"] * len(props):
            raise ValueError("PLY 데이터가 헤더의 정점 수보다 짧습니다.")
        from plyfile import PlyData

        data = PlyData.read(
            path, mmap="c", known_list_len={"face": {"vertex_indices": 3}}
        )
        vertices = data["vertex"].data
        if not {"x", "y", "z"} <= set(props):
            raise ValueError("정점 좌표가 없습니다.")
        for name in props:
            for offset in range(0, len(vertices), 65536):
                if not np.isfinite(vertices[name][offset : offset + 65536]).all():
                    raise ValueError("PLY 데이터에 NaN 또는 무한대가 있습니다.")
        item.update(vertices=len(vertices))
        if elements.get("face"):
            faces = data["face"].data["vertex_indices"]
            if any(
                len(face) != 3 or min(face) < 0 or max(face) >= len(vertices)
                for face in faces
            ):
                raise ValueError("삼각형 인덱스가 잘못되었습니다.")
            item.update(
                kind="mesh",
                format="ply",
                triangles=len(faces),
                colors={"red", "green", "blue"} <= set(props),
                valid=True,
                usable=True,
            )
            return item
        gaussian = any(
            p.startswith(("f_dc_", "f_rest_", "scale_", "rot_")) or p == "opacity"
            for p in props
        )
        if not gaussian:
            item.update(
                kind="point_cloud",
                error="일반 점 구름입니다. 현재 결과 뷰어의 메시·Object-Aware Gaussian 형식이 아닙니다.",
            )
            return item
        required = {
            "x",
            "y",
            "z",
            "opacity",
            "objectmark_score",
            *[f"f_dc_{i}" for i in range(3)],
            "scale_0",
            "scale_1",
            *[f"rot_{i}" for i in range(4)],
        }
        rest = {p for p in props if p.startswith("f_rest_")}
        degree = next(
            (
                d
                for d in range(4)
                if rest == {f"f_rest_{i}" for i in range(3 * ((d + 1) ** 2 - 1))}
            ),
            None,
        )
        scale = {p for p in props if p.startswith("scale_")}
        rot = {p for p in props if p.startswith("rot_")}
        if (
            not required <= set(props)
            or degree is None
            or scale != {"scale_0", "scale_1"}
            or rot != {f"rot_{i}" for i in range(4)}
        ):
            item.update(
                kind="unsupported",
                error="현재 Object-Aware 2DGS 스키마와 다릅니다. 2개 scale, 4개 rotation, SH 및 objectmark_score가 필요합니다.",
            )
            return item
        for start in range(0, len(vertices), 65536):
            v = vertices[start : start + 65536]
            if any(np.any(np.abs(v[k]) > 1e12) for k in ("x", "y", "z")) or any(
                np.any(np.abs(v[k]) > 1e6)
                for k in props
                if k.startswith(("f_dc_", "f_rest_", "rot_"))
            ):
                raise ValueError(
                    "Gaussian 수치가 현재 렌더러의 안전 범위를 초과했습니다."
                )
            if np.any(sum(v[f"rot_{i}"] ** 2 for i in range(4)) < 1e-12):
                raise ValueError("Gaussian 회전이 유효하지 않습니다.")
            if any(
                np.any(v[k] > LOG_SCALE_MAX) or np.any(v[k] < LOG_SCALE_MIN)
                for k in ("scale_0", "scale_1")
            ):
                raise ValueError("Gaussian 크기가 렌더링 범위를 초과했습니다.")
        xyz = np.column_stack([vertices[k] for k in ("x", "y", "z")]).astype(np.float64)
        center = np.median(xyz, axis=0)
        radius = float(np.percentile(np.linalg.norm(xyz - center, axis=1), 90))
        item.update(
            kind="gaussian",
            format="ply",
            sh_degree=degree,
            target=center.tolist(),
            radius=max(radius, 0.001),
            valid=True,
            usable=True,
            note="독립 결과입니다. 현재 데이터셋의 학습 완료를 뜻하지 않습니다. 촬영 카메라 없이 자유 시점으로 표시합니다.",
        )
    except Exception as exc:
        item.update(kind="invalid", valid=False, usable=False, error=str(exc))
    return item


def import_result(store, pid, folder, finding):
    """Owned copies only. Revalidate after copying to close scan/import races."""
    import shutil
    import uuid
    from studio.doctor import sha256, atomic_json

    root = store.path(pid)
    source = Path(folder) / finding["path"]
    check = inspect_result(source, folder)
    if not check["valid"]:
        raise ValueError(check.get("error", "결과 파일을 사용할 수 없습니다."))
    identity = sha256(source)
    artifact_id = str(uuid.uuid4())
    work = root / "result-import" / artifact_id
    work.mkdir(parents=True)
    if check["kind"] == "gaussian":
        dest = work / "point_cloud/iteration_0/point_cloud.ply"
        dest.parent.mkdir(parents=True)
        shutil.copyfile(source, dest)
        copied = inspect_result(dest, work)
        if (
            not copied["valid"]
            or sha256(dest) != identity
            or sha256(source) != identity
        ):
            raise ValueError("복사 중 결과 파일이 변경되었습니다. 다시 분석하세요.")
        (work / "cfg_args").write_text(
            f"Namespace(sh_degree={check['sh_degree']}, white_background=False)"
        )
        record = {
            **check,
            "id": artifact_id,
            "source_path": str(source),
            "source_sha256": identity,
            "path": str(dest.relative_to(root)),
            "model": str(work.relative_to(root)),
            "dataset_link": "independent",
            "iteration": 0,
        }

        def finish(doc):
            doc.setdefault("result_artifacts", []).append(record)
            doc["active_gaussian_artifact"] = artifact_id

        store.update(pid, finish)
    else:
        # Existing mesh adapter validates and preserves colour. It creates a unique owned output.
        from studio import api

        if api.store is not store:
            raise RuntimeError("프로젝트 저장소가 일치하지 않습니다.")
        api._import_mesh(pid, source, None)
        mesh = store.get(pid)["mesh"]
        if sha256(source) != identity:
            raise ValueError("가져오는 동안 원본 파일이 변경되었습니다.")
        record = {
            **check,
            "id": artifact_id,
            "source_path": str(source),
            "source_sha256": identity,
            "path": mesh["path"],
            "mesh": mesh,
            "dataset_link": "independent",
        }
        store.update(
            pid, lambda doc: doc.setdefault("result_artifacts", []).append(record)
        )
    atomic_json(work / "artifact.json", record)
    return record


def safe_model_config(model, *, source=None, target=None):
    """Original render.py uses eval(cfg_args); supply only a literal, typed Namespace."""
    import ast
    from studio.task_settings import argument_defaults

    path = Path(model) / "cfg_args"
    if path.stat().st_size > 16384:
        raise ValueError("학습 모델 설정 파일이 너무 큽니다.")
    node = ast.parse(path.read_text(), mode="eval").body
    if (
        not isinstance(node, ast.Call)
        or not isinstance(node.func, ast.Name)
        or node.func.id != "Namespace"
        or node.args
        or any(k.arg is None for k in node.keywords)
    ):
        raise ValueError("학습 모델 설정은 리터럴 Namespace 형식이어야 합니다.")
    try:
        raw = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
    except (ValueError, TypeError):
        raise ValueError(
            "학습 모델 설정에 실행 가능한 표현식이 있어 사용하지 않습니다."
        )
    defaults = argument_defaults()
    keys = (
        "sh_degree",
        "source_path",
        "model_path",
        "images",
        "resolution",
        "white_background",
        "data_device",
        "eval",
        "render_items",
    )
    clean = {k: raw.get(k, defaults[k]) for k in keys}
    if any(type(clean[k]) is not type(defaults[k]) for k in keys):
        raise ValueError("학습 모델 설정의 값 형식이 잘못되었습니다.")
    if (
        not 0 <= clean["sh_degree"] <= 3
        or clean["resolution"] == 0
        or not -1 <= clean["resolution"] <= 8192
    ):
        raise ValueError("학습 모델 설정의 SH 차수·해상도가 잘못되었습니다.")
    if (
        clean["data_device"] not in ("cuda", "cpu")
        or clean["render_items"] != defaults["render_items"]
    ):
        raise ValueError("현재 원본 렌더러와 다른 내부 설정은 가져올 수 없습니다.")
    clean["images"] = "images"
    if source is not None:
        clean["source_path"] = str(source)
    if target is not None:
        clean["model_path"] = str(target)
    return "Namespace(" + ", ".join(k + "=" + repr(v) for k, v in clean.items()) + ")"
