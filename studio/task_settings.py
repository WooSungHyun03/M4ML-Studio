"""Provider-owned task settings: literal defaults, bounded validation, execution snapshots.

No CUDA imports. Scientific formulas remain in upstream files. Ranges below are
application safety limits, not claims of scientifically optimal parameter ranges.
"""

import ast
import copy
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1


def argument_defaults():
    tree = ast.parse((ROOT / "arguments/__init__.py").read_text())
    values = {}
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name in {
            "ModelParams",
            "OptimizationParams",
            "PipelineParams",
        }:
            for node in ast.walk(cls):
                if isinstance(node, ast.Assign) and len(node.targets) == 1:
                    t = node.targets[0]
                    if (
                        isinstance(t, ast.Attribute)
                        and isinstance(t.value, ast.Name)
                        and t.value.id == "self"
                    ):
                        try:
                            values[t.attr.lstrip("_")] = ast.literal_eval(node.value)
                        except (ValueError, TypeError):
                            pass
    return values


def field(
    id,
    label,
    default,
    type="number",
    lo=None,
    hi=None,
    *,
    native=None,
    source="",
    description="",
    advanced=False,
    options=None,
    effect="next_run",
):
    description = description or (
        label
        + " 값을 변경합니다. "
        + (
            "실행 결과에 영향을 줍니다."
            if effect == "next_run"
            else "표시에만 적용합니다."
        )
    )
    return dict(
        id=id,
        label=label,
        default=default,
        type=type,
        min=lo,
        max=hi,
        native=native or id,
        source=source,
        description=description,
        advanced=advanced,
        options=options,
        effect=effect,
        scope="project_display" if effect == "display" else "project_processing",
        restart=effect != "display",
    )


def definitions(capability, key):
    d = argument_defaults()

    def train(id, native, label, lo, hi, advanced=True, description=""):
        default = d[native]
        return field(
            id,
            label,
            default,
            "integer" if type(default) is int else "number",
            lo,
            hi,
            native=native,
            source="arguments/__init__.py; train.py",
            description=description,
            advanced=advanced,
        )

    if (capability, key) == ("training", "object_aware_2dgs"):
        return [
            train("iterations", "iterations", "학습 횟수", 100, 100000, False),
            train(
                "image_resolution",
                "resolution",
                "학습 사진 해상도",
                -1,
                8192,
                False,
                "-1: 원본 코드의 자동 해상도. 1·2·4·8: 축소 배율, 그 외 양수: 가로 픽셀 수.",
            ),
            field(
                "checkpoint_every",
                "저장 간격",
                2500,
                "integer",
                10,
                50000,
                source="studio/providers/training_object_aware.py",
                description="반복 횟수 단위. 마지막 반복도 저장합니다.",
            ),
            train(
                "alpha_weight", "lambda_pa", "알파 Polarization 가중치", 0, 10, False
            ),
            train(
                "object_weight", "lambda_po", "객체 Polarization 가중치", 0, 10, False
            ),
            train(
                "normal_weight",
                "lambda_normal",
                "법선 가중치",
                0,
                10,
                False,
                "원본 코드에서 7,000회 이후 적용합니다.",
            ),
            train(
                "distortion_weight",
                "lambda_dist",
                "깊이 왜곡 가중치",
                0,
                100,
                False,
                "원본 코드에서 3,000회 이후 적용합니다.",
            ),
            *[
                train(id, native, label, 0, hi)
                for id, native, label, hi in [
                    (
                        "position_lr_initial",
                        "position_lr_init",
                        "위치 초기 학습률",
                        0.1,
                    ),
                    ("position_lr_final", "position_lr_final", "위치 최종 학습률", 0.1),
                    ("feature_lr", "feature_lr", "색상 학습률", 1),
                    ("opacity_lr", "opacity_lr", "불투명도 학습률", 1),
                    ("object_lr", "objectmark_lr", "객체 점수 학습률", 1),
                    ("scale_lr", "scaling_lr", "크기 학습률", 1),
                    ("rotation_lr", "rotation_lr", "회전 학습률", 1),
                    (
                        "densify_threshold",
                        "densify_grad_threshold",
                        "밀도 확장 기울기 기준",
                        1,
                    ),
                    ("opacity_cull", "opacity_cull", "불투명도 제거 기준", 1),
                    (
                        "object_prune_threshold",
                        "objectmark_prune_threshold",
                        "객체 점수 제거 기준",
                        1,
                    ),
                ]
            ],
            train(
                "lr_schedule_steps",
                "position_lr_max_steps",
                "위치 학습률 스케줄 길이",
                1,
                100000,
            ),
            train("lr_delay", "position_lr_delay_mult", "위치 학습률 지연 배율", 0, 1),
            train(
                "dense_fraction", "percent_dense", "밀도 확장 크기 비율", 0.000001, 1
            ),
            train(
                "densify_interval", "densification_interval", "밀도 확장 간격", 1, 10000
            ),
            train("densify_from", "densify_from_iter", "밀도 확장 시작", 0, 100000),
            train("densify_until", "densify_until_iter", "밀도 확장 종료", 1, 100000),
            train(
                "opacity_reset_interval",
                "opacity_reset_interval",
                "불투명도 초기화 간격",
                1,
                100000,
            ),
            train(
                "object_prune_from",
                "objectmark_prune_from_iter",
                "객체 제거 시작",
                0,
                100000,
            ),
            train(
                "object_prune_interval",
                "objectmark_prune_interval",
                "객체 제거 간격",
                1,
                100000,
            ),
            train("sh_degree", "sh_degree", "SH 차수", 0, 3),
            field(
                "white_background",
                "흰색 학습 배경",
                d["white_background"],
                "boolean",
                source="arguments/__init__.py; train.py",
                advanced=True,
            ),
        ]
    if (capability, key) == ("camera", "colmap"):
        src = "COLMAP4.2.1 feature_extractor / exhaustive_matcher / mapper -h"
        return [
            field(
                "max_image_size",
                "사진 처리 최대 크기",
                -1,
                "integer",
                -1,
                8192,
                native="FeatureExtraction.max_image_size",
                source=src,
                description="-1: 엔진 기본값, 양수: 긴 변의 최대 픽셀 수.",
            ),
            field(
                "matching",
                "사진 매칭",
                "exhaustive",
                "choice",
                options=["exhaustive", "sequential"],
                source="studio/providers/camera_colmap.py",
                description="전체 쌍 / 촬영 순서. 순차 매칭은 순서가 있는 사진에 사용하세요.",
            ),
            field(
                "use_gpu",
                "GPU 사용",
                True,
                "boolean",
                source="studio/engines.py",
                description="특징점 추출·매칭에 적용. 카메라 자세 추정은 CPU에서 실행합니다.",
            ),
            field(
                "camera_model",
                "카메라 모델",
                "SIMPLE_RADIAL",
                "choice",
                options=[
                    "SIMPLE_RADIAL",
                    "RADIAL",
                    "OPENCV",
                    "PINHOLE",
                    "SIMPLE_PINHOLE",
                ],
                native="ImageReader.camera_model",
                source=src,
            ),
            field(
                "single_camera",
                "하나의 카메라 공유",
                False,
                "boolean",
                native="ImageReader.single_camera",
                source=src,
                advanced=True,
            ),
            field(
                "max_features",
                "최대 특징점 수",
                8192,
                "integer",
                512,
                65536,
                native="SiftExtraction.max_num_features",
                source=src,
                advanced=True,
            ),
            field(
                "matching_error",
                "매칭 기하 오차 한계",
                4.0,
                "number",
                0.1,
                32,
                native="TwoViewGeometry.max_error",
                source=src,
                advanced=True,
            ),
            field(
                "minimum_matches",
                "최소 매칭 수",
                15,
                "integer",
                8,
                100,
                native="Mapper.min_num_matches",
                source=src,
                advanced=True,
            ),
            field(
                "refine_focal",
                "초점 거리 보정",
                True,
                "boolean",
                native="Mapper.ba_refine_focal_length",
                source=src,
                advanced=True,
            ),
            field(
                "refine_principal",
                "주점 보정",
                False,
                "boolean",
                native="Mapper.ba_refine_principal_point",
                source=src,
                advanced=True,
            ),
            field(
                "threads",
                "CPU 스레드",
                min(__import__("os").cpu_count() or 4, 16),
                "integer",
                1,
                64,
                source="studio/providers/camera_colmap.py",
                advanced=True,
            ),
        ]
    if (capability, key) == ("segmentation", "sam31"):
        src = "vendor/sam3/sam3/model_builder.py:1183; sam3_multiplex_tracking.py:2936"
        return [
            field(
                "propagation_radius",
                "주변 다시 전파 범위",
                2,
                "integer",
                1,
                25,
                source="studio/sam31.py radius; MaskStage.tsx",
                description="주변만 다시 전파할 때 앞뒤 사진 수입니다. 전체 전파에는 적용하지 않습니다.",
            ),
            field(
                "fill_hole_area",
                "작은 구멍 채우기",
                0,
                "integer",
                0,
                4096,
                source=src,
                description="공식 모델의 후처리 면적 기준(픽셀). 0은 사용 안 함. 다음 클릭·전파부터 적용합니다.",
            ),
            field(
                "sprinkle_removal_area",
                "작은 영역 제거",
                0,
                "integer",
                0,
                4096,
                source=src,
                description="공식 모델의 작은 연결 영역 제거 기준(픽셀). 0은 사용 안 함.",
            ),
            field(
                "coverage_warning",
                "넓은 마스크 경고 기준",
                0.98,
                "number",
                0.5,
                1,
                source="studio/sam31.py",
                description="사진에서 마스크가 차지하는 비율. 모델 신뢰도가 아닌 검토용 경고 기준입니다.",
                advanced=True,
            ),
            field(
                "offload_video_to_cpu",
                "사진을 CPU 메모리에 보관",
                True,
                "boolean",
                source="studio/sam31.py; sam31_session.py",
                description="GPU 메모리를 절약합니다. 현재 세션의 다음 사진 준비·전파부터 적용합니다.",
                advanced=True,
            ),
        ]
    if (capability, key) == ("mesh", "object_aware_tsdf"):
        return [
            field(
                "mesh_res",
                "생성 해상도",
                1024,
                "integer",
                64,
                2048,
                source="render.py:44",
                description="TSDF 격자 해상도. 높이면 메모리·처리량이 증가합니다. 표시 해상도와 별개입니다.",
            ),
            field(
                "voxel_size",
                "복셀 크기",
                -1.0,
                "number",
                -1,
                10,
                source="render.py:39",
                description="-1: 장면 크기와 생성 해상도로 자동 계산.",
                advanced=True,
            ),
            field(
                "sdf_trunc",
                "TSDF 절단 거리",
                -1.0,
                "number",
                -1,
                100,
                source="render.py:41",
                description="-1: 원본 코드의 자동 계산.",
                advanced=True,
            ),
            field(
                "depth_trunc",
                "깊이 절단 거리",
                -1.0,
                "number",
                -1,
                10000,
                source="render.py:40",
                description="-1: 장면 크기에서 자동 계산.",
                advanced=True,
            ),
            field(
                "num_cluster",
                "보존할 연결 요소 수",
                50,
                "integer",
                1,
                1000,
                source="render.py:42",
                description="원본 메시 후처리에서 큰 연결 요소를 보존합니다.",
                advanced=True,
            ),
            field(
                "unbounded",
                "비한정 장면 추출",
                False,
                "boolean",
                source="render.py:43",
                advanced=True,
            ),
        ]
    if capability == "review" and key == "studio_review":
        return [
            field(
                "review_filter",
                "사진 목록 필터",
                "all",
                "choice",
                options=["all", "unreviewed", "warnings", "reviewed"],
                source="frontend/src/stages/MaskStage.tsx",
                effect="display",
                description="오른쪽 사진 목록을 필터링합니다. 현재 사진과 이전·다음 이동 순서는 유지합니다.",
            ),
            field(
                "overlay_opacity",
                "마스크 투명도",
                0.4,
                "number",
                0,
                1,
                source="frontend/src/MaskEditor.tsx",
                effect="display",
            ),
            field(
                "overlay_color",
                "마스크 색상",
                "#f0a53a",
                "color",
                source="frontend/src/MaskEditor.tsx",
                effect="display",
            ),
            field(
                "show_boundary",
                "경계 표시",
                False,
                "boolean",
                source="frontend/src/MaskEditor.tsx",
                effect="display",
            ),
            field(
                "mask_only",
                "마스크만 보기",
                False,
                "boolean",
                source="frontend/src/MaskEditor.tsx",
                effect="display",
            ),
            field(
                "auto_next",
                "저장 후 다음 사진",
                False,
                "boolean",
                source="frontend/src/stages/MaskStage.tsx",
                effect="display",
            ),
            field(
                "warnings_first",
                "경고 사진 우선",
                False,
                "boolean",
                source="frontend/src/stages/MaskStage.tsx",
                effect="display",
            ),
            field(
                "brush_size",
                "브러시 크기",
                18,
                "integer",
                2,
                100,
                source="frontend/src/MaskEditor.tsx",
                effect="display",
            ),
        ]
    if capability == "view" and key == "studio_view":
        return [
            field(
                "render_scale",
                "표시 해상도 배율",
                1.0,
                "number",
                0.25,
                2,
                source="frontend/src/MeshViewer.tsx; GaussianViewer.tsx",
                effect="display",
                description="3D 렌더링 영역에만 적용합니다. UI 글자 크기는 유지합니다.",
            ),
            field(
                "background",
                "뷰포트 배경",
                "#1c1c20",
                "color",
                source="frontend/src/MeshViewer.tsx",
                effect="display",
            ),
            field(
                "grid",
                "그리드",
                True,
                "boolean",
                source="frontend/src/MeshViewer.tsx",
                effect="display",
            ),
            field(
                "axes",
                "좌표축",
                False,
                "boolean",
                source="frontend/src/MeshViewer.tsx",
                effect="display",
            ),
            field(
                "orthographic",
                "직교 투영",
                False,
                "boolean",
                source="frontend/src/MeshViewer.tsx",
                effect="display",
                description="메시 뷰어에 적용합니다. Gaussian 원본 렌더러는 원근 투영만 지원합니다.",
            ),
            field(
                "rotate_speed",
                "회전 감도",
                1.0,
                "number",
                0.1,
                5,
                source="Three.js OrbitControls.rotateSpeed",
                effect="display",
            ),
            field(
                "zoom_speed",
                "확대 감도",
                1.0,
                "number",
                0.1,
                5,
                source="Three.js OrbitControls.zoomSpeed",
                effect="display",
            ),
            field(
                "pan_speed",
                "이동 감도",
                1.0,
                "number",
                0.1,
                5,
                source="Three.js OrbitControls.panSpeed",
                effect="display",
            ),
            field(
                "light_azimuth",
                "주 조명 방향",
                -35.0,
                "number",
                -180,
                180,
                source="frontend/src/MeshViewer.tsx",
                effect="display",
                advanced=True,
            ),
            field(
                "mesh_mode",
                "메시 표시 모드",
                "color",
                "choice",
                options=["color", "vertex", "shaded", "wire", "normals", "points"],
                source="frontend/src/MeshViewer.tsx",
                effect="display",
            ),
            field(
                "gaussian_mode",
                "Gaussian 표시 모드",
                "rgb",
                "choice",
                options=["rgb", "alpha", "depth", "normal", "objectmark"],
                source="studio/providers/render_gaussian_remote.py",
                effect="display",
            ),
            field(
                "light",
                "조명 강도",
                1.0,
                "number",
                0,
                5,
                source="frontend/src/MeshViewer.tsx",
                effect="display",
                description="메시의 셰이딩·정점 색상 모드에 적용합니다. 원본 색상 모드는 조명을 사용하지 않습니다.",
            ),
            field(
                "point_size",
                "포인트 크기",
                2.0,
                "number",
                0.5,
                12,
                source="frontend/src/MeshViewer.tsx",
                effect="display",
            ),
            field(
                "fov",
                "시야각",
                35.0,
                "number",
                15,
                100,
                source="Three.js PerspectiveCamera",
                effect="display",
                advanced=True,
            ),
            field(
                "near",
                "가까운 절단면",
                0.001,
                "number",
                0.00001,
                10,
                source="Three.js Camera.near; gaussian_protocol",
                effect="display",
                advanced=True,
            ),
            field(
                "far",
                "먼 절단면",
                100000.0,
                "number",
                1,
                100000,
                source="Three.js Camera.far; gaussian_protocol",
                effect="display",
                advanced=True,
            ),
            field(
                "screenshot_scale",
                "스크린샷 배율",
                1.0,
                "number",
                0.5,
                4,
                source="frontend/src/MeshViewer.tsx",
                effect="display",
                advanced=True,
            ),
        ]
    return []


def schema(group):
    if group in ("review", "view"):
        key = "studio_" + group
        fields = definitions(group, key)
    else:
        from studio.engines import provider

        engine = provider(group)
        key = engine.key
        fields = engine.task_settings_schema()
    for f in fields:
        k = f["id"]
        if group == "training":
            f["section"] = (
                "손실 가중치"
                if k.endswith("_weight")
                else (
                    "학습률"
                    if "_lr" in k or k.startswith("lr_")
                    else (
                        "밀도 확장·제거"
                        if any(
                            v in k
                            for v in ("dens", "prune", "opacity_reset", "opacity_cull")
                        )
                        else "학습 실행"
                    )
                )
            )
        elif group == "view":
            f["section"] = (
                "메시 표시"
                if k
                in (
                    "grid",
                    "axes",
                    "orthographic",
                    "light",
                    "light_azimuth",
                    "point_size",
                    "mesh_mode",
                )
                else (
                    "카메라"
                    if k
                    in ("fov", "near", "far", "rotate_speed", "zoom_speed", "pan_speed")
                    else "렌더링·저장"
                )
            )
            if f["section"] == "메시 표시" and k != "orthographic":
                f["description"] = "메시 뷰어에 적용합니다. " + f["description"]
        elif group == "review":
            f["section"] = (
                "검토 목록"
                if k in ("auto_next", "warnings_first", "review_filter")
                else "마스크 표시·편집"
            )
        else:
            f["section"] = "처리 설정"
        f["gpu_impact"] = (
            "설정에 따라 GPU 메모리·처리량이 달라질 수 있습니다."
            if group in ("training", "camera", "segmentation", "mesh", "view")
            else "추론·학습 GPU 계산에는 영향을 주지 않습니다."
        )
    presets = {}
    if group == "training" and key == "object_aware_2dgs":
        presets = {
            "빠름": {"iterations": 3000},
            "균형": {"iterations": 15000},
            "높음": {"iterations": 30000},
        }
    if group == "camera" and key == "colmap":
        presets = {
            "빠름": {"max_image_size": 1600, "max_features": 4096},
            "균형": {"max_image_size": 2400, "max_features": 8192},
            "높음": {"max_image_size": -1, "max_features": 16384},
        }
    return dict(
        group=group,
        provider=key,
        version=SCHEMA_VERSION,
        fields=fields,
        presets=presets,
        policy=(
            "즉시 표시 적용 · 원본 파일은 변경하지 않습니다."
            if group in ("view", "review")
            else "다음 실행부터 적용 · 실행 중에는 변경할 수 없습니다. 기존 결과는 보존합니다."
        ),
    )


def validate(group, values):
    s = schema(group)
    fields = {f["id"]: f for f in s["fields"]}
    if set(values) - fields.keys():
        raise ValueError(
            "지원하지 않는 설정입니다: "
            + ", ".join(sorted(set(values) - fields.keys()))
        )
    result = {f["id"]: copy.deepcopy(f["default"]) for f in fields.values()}
    for key, value in values.items():
        f = fields[key]
        t = f["type"]
        valid = (
            type(value) is bool
            if t == "boolean"
            else (
                type(value) is int
                if t == "integer"
                else (
                    type(value) in (int, float) and math.isfinite(value)
                    if t == "number"
                    else isinstance(value, str)
                )
            )
        )
        if not valid:
            raise ValueError(f"{f['label']}: 값의 형식을 확인하세요.")
        if t in ("number", "integer") and not f["min"] <= value <= f["max"]:
            raise ValueError(f"{f['label']}: {f['min']}–{f['max']} 범위로 입력하세요.")
        if t == "choice" and value not in f["options"]:
            raise ValueError(f"{f['label']}: 지원하는 항목을 선택하세요.")
        if t == "color" and not __import__("re").fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("색상은 #RRGGBB 형식이어야 합니다.")
        result[key] = value
    if group == "training" and s["provider"] == "object_aware_2dgs":
        if result["image_resolution"] == 0:
            raise ValueError("학습 사진 해상도는 -1 또는 양수로 지정하세요.")
        if result["position_lr_final"] > result["position_lr_initial"]:
            raise ValueError("최종 위치 학습률은 초기값 이하여야 합니다.")
        if result["densify_from"] >= result["densify_until"]:
            raise ValueError("밀도 확장 종료는 시작보다 커야 합니다.")
    if (
        group == "camera"
        and s["provider"] == "colmap"
        and result["max_image_size"] not in (-1,)
        and result["max_image_size"] < 64
    ):
        raise ValueError("사진 처리 크기는 -1 또는 64 이상이어야 합니다.")
    if group == "mesh" and s["provider"] == "object_aware_tsdf":
        for k in ("voxel_size", "sdf_trunc", "depth_trunc"):
            if result[k] != -1 and result[k] <= 0:
                raise ValueError("추출 거리는 -1 또는 양수로 지정하세요.")
    if group == "view" and result["far"] <= result["near"]:
        raise ValueError("먼 절단면은 가까운 절단면보다 커야 합니다.")
    return result


def effective(project, group):
    s = schema(group)
    version = project.get("task_settings", {}).get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise ValueError("이 프로젝트의 설정 버전은 현재 앱에서 지원하지 않습니다.")
    namespaces = project.get("task_settings", {}).get("values", {})
    namespace = group + ":" + s["provider"]
    values = namespaces.get(namespace, {})
    if (
        namespace not in namespaces
        and group == "training"
        and s["provider"] == "object_aware_2dgs"
    ):
        legacy = project.get("settings", {}).get("iterations")
        if type(legacy) is int:
            values = {"iterations": legacy}
    return validate(group, values)


def snapshot(project, group):
    s = schema(group)
    values = effective(project, group)
    return {
        "schema_version": SCHEMA_VERSION,
        "group": group,
        "provider": s["provider"],
        "values": values,
        "parameters": {f["native"]: values[f["id"]] for f in s["fields"]},
    }


GROUPS = ("camera", "segmentation", "review", "training", "mesh", "view")
STAGES = {
    "colmap": "camera",
    "preview": "segmentation",
    "sam": "segmentation",
    "train": "training",
    "mesh": "mesh",
}


def bundle(project):
    groups = {g: {**schema(g), "values": effective(project, g)} for g in GROUPS}
    last = project.get("training_partial", {}).get("fingerprint", {}).get(
        "settings"
    ) or project.get("training", {}).get("settings_snapshot")
    if last:
        groups["training"]["last_execution"] = last
    return groups


def save(project, group, values):
    if group not in GROUPS:
        raise ValueError("지원하지 않는 설정 그룹입니다.")
    checked = validate(group, values)
    state = project.setdefault(
        "task_settings", {"schema_version": SCHEMA_VERSION, "values": {}}
    )
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("지원하지 않는 설정 버전입니다.")
    state.setdefault("values", {})[group + ":" + schema(group)["provider"]] = checked


def execution(project, stage, request, explicit=None):
    """Freeze the provider's validated configuration; accept legacy per-run API overrides."""
    if stage not in STAGES:
        return dict(request)
    group = STAGES[stage]
    out = dict(request)
    values = effective(project, group)
    mappings = {
        "training": {"iterations": "iterations", "resolution": "image_resolution"},
        "camera": {"matching": "matching"},
        "mesh": {"mesh_res": "mesh_res"},
    }.get(group, {})
    for old, new in mappings.items():
        if old in (explicit if explicit is not None else request):
            values[new] = request[old]
    values = validate(group, values)
    s = schema(group)
    snap = {
        "schema_version": SCHEMA_VERSION,
        "group": group,
        "provider": s["provider"],
        "values": values,
        "parameters": {f["native"]: values[f["id"]] for f in s["fields"]},
    }
    out.update(settings_snapshot=snap, parameters=snap["parameters"])
    for old, new in mappings.items():
        out[old] = values[new]
    if group == "camera" and not values["use_gpu"]:
        out["cpu_fallback"] = True
    if stage == "train":
        mesh = execution(
            project,
            "mesh",
            (
                {"mesh_res": request["mesh_res"]}
                if "mesh_res" in (explicit if explicit is not None else request)
                else {}
            ),
        )
        out["mesh_request"] = mesh
    return out


def require_resume_settings(partial, request):
    previous = (partial or {}).get("fingerprint", {}).get("settings")
    if not previous or previous != request.get("settings_snapshot"):
        raise ValueError(
            "저장 지점의 실행 설정과 현재 설정이 다릅니다. 해당 실행의 설정으로 복원하거나 새로 학습하세요. 이전 파일은 보존했습니다."
        )
