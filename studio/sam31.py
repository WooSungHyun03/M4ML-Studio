"""Official SAM3.1 only; camera-ordered registered views and aligned binary outputs."""

import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image

from studio.colmap import loader, read_model, validate_scene
from studio.doctor import atomic_json, sha256


def ordered_views(scene):
    cameras, images = read_model(Path(scene) / "sparse/0")
    reader = loader()
    views = {}
    for pose in images.values():
        rotation = reader.qvec2rotmat(pose.qvec)
        views[pose.name] = {
            "name": pose.name,
            "center": -rotation.T @ pose.tvec,
            "direction": rotation.T[:, 2],
        }
    remaining = set(views)
    current = min(remaining)
    ordered = []
    centers = np.array([v["center"] for v in views.values()])
    scale = max(float(np.linalg.norm(centers - centers.mean(0), axis=1).mean()), 1e-6)
    while remaining:
        remaining.remove(current)
        v = views[current]
        angle = (
            0.0
            if not ordered
            else float(
                np.degrees(
                    np.arccos(
                        np.clip(
                            np.dot(
                                v["direction"], views[ordered[-1]["name"]]["direction"]
                            ),
                            -1,
                            1,
                        )
                    )
                )
            )
        )
        distance = (
            0.0
            if not ordered
            else float(
                np.linalg.norm(v["center"] - views[ordered[-1]["name"]]["center"])
                / scale
            )
        )
        ordered.append(
            {
                "name": current,
                "center": v["center"].tolist(),
                "direction": v["direction"].tolist(),
                "view_angle_deg": angle,
                "relative_distance": distance,
                "discontinuity": angle > 45 or distance > 0.8,
            }
        )
        if remaining:
            current = min(
                remaining,
                key=lambda name: (
                    float(np.linalg.norm(views[name]["center"] - v["center"]) / scale)
                    + float(
                        np.arccos(
                            np.clip(
                                np.dot(views[name]["direction"], v["direction"]), -1, 1
                            )
                        )
                    ),
                    name,
                ),
            )
    return ordered


def validate_mask(path, size):
    with Image.open(path) as image:
        image.load()
        a = np.asarray(image)
        if image.mode != "L" or image.size != tuple(size) or a.dtype != np.uint8:
            raise ValueError("마스크 형식 또는 크기가 사진과 다릅니다.")
        if not np.isin(a, [0, 255]).all() or not np.any(a == 255):
            raise ValueError("마스크가 비어 있거나 이진 마스크가 아닙니다.")
    return {
        "area": int(np.count_nonzero(a)),
        "coverage": float(np.count_nonzero(a) / a.size),
        "sha256": sha256(path),
        "size": list(size),
    }


def segment(
    scene, checkpoint, reference, points, labels, output, *, preview=False, radius=None
):
    import torch
    from sam3.model_builder import build_sam3_multiplex_video_predictor

    scene, checkpoint, output = Path(scene), Path(checkpoint), Path(output)
    names = validate_scene(scene)
    if (
        reference not in names
        or not points
        or len(points) != len(labels)
        or 1 not in labels
    ):
        raise ValueError("등록 사진에서 대상 영역을 한 번 이상 선택하세요.")
    if any(label not in (0, 1) for label in labels):
        raise ValueError("클릭 유형이 유효하지 않습니다.")
    if (
        not torch.cuda.is_available()
        or torch.__version__.split("+")[0] != "2.5.1"
        or torch.version.cuda != "11.8"
    ):
        raise RuntimeError("검증된 GPU 처리 런타임이 필요합니다. 설정 › 처리 장치를 확인하세요.")
    output.mkdir(parents=True, exist_ok=False)
    order = ordered_views(scene)
    sizes = {}
    for name in names:
        with Image.open(scene / "images" / name) as image:
            sizes[name] = image.size
    width, height = max(s[0] for s in sizes.values()), max(s[1] for s in sizes.values())
    # Padding preserves physical image pixel coordinates and permits mixed cameras.
    # Upstream video output assumes a common size; crop each output to its image.
    frame_map = [
        {
            **view,
            "frame_index": idx,
            "size": list(sizes[view["name"]]),
            "padding_xy": [
                (width - sizes[view["name"]][0]) // 2,
                (height - sizes[view["name"]][1]) // 2,
            ],
        }
        for idx, view in enumerate(order)
    ]
    atomic_json(output / "frames.json", frame_map)
    ref = next(v for v in frame_map if v["name"] == reference)
    if radius is not None and (not isinstance(radius, int) or not 1 <= radius <= 25):
        raise ValueError("주변 전파 범위가 유효하지 않습니다.")
    expected = (
        [ref]
        if preview
        else [
            v
            for v in frame_map
            if radius is None or abs(v["frame_index"] - ref["frame_index"]) <= radius
        ]
    )
    rw, rh = sizes[reference]
    if any(not (0 <= x < rw and 0 <= y < rh) for x, y in points):
        raise ValueError("클릭 좌표가 사진 밖에 있습니다.")
    prompts = [
        [(x + ref["padding_xy"][0]) / width, (y + ref["padding_xy"][1]) / height]
        for x, y in points
    ]
    atomic_json(
        output / "prompts.json",
        {
            "reference": reference,
            "points_pixels": points,
            "labels": labels,
            "checkpoint_sha256": sha256(checkpoint),
            "preview": preview,
        },
    )
    predictor = build_sam3_multiplex_video_predictor(
        checkpoint_path=str(checkpoint.resolve()),
        use_fa3=False,
        use_rope_real=False,
        compile=False,
        warm_up=False,
        async_loading_frames=False,
    )
    # Fail closed if the permissive upstream checkpoint loader left any parameters uninitialized.
    state = torch.load(checkpoint, weights_only=True, map_location="cpu", mmap=True)
    state = state.get("model", state)
    actual = predictor.model.state_dict()
    if set(state) != set(actual) or any(
        state[k].shape != actual[k].shape for k in state
    ):
        raise ValueError("객체 선택 모델 파일이 공식 모델 구조와 일치하지 않습니다.")
    del state, actual
    report = {}
    with tempfile.TemporaryDirectory(prefix=".frames-", dir=output) as directory:
        for v in frame_map:
            canvas = Image.new("RGB", (width, height))
            with Image.open(scene / "images" / v["name"]) as image:
                canvas.paste(image.convert("RGB"), tuple(v["padding_xy"]))
            canvas.save(Path(directory) / f"{v['frame_index']:06d}.png")
        session = predictor.handle_request(
            dict(
                type="start_session", resource_path=directory, offload_video_to_cpu=True
            )
        )["session_id"]

        def save(response):
            idx, outputs = response["frame_index"], response["outputs"]
            view = frame_map[idx]
            ids = np.asarray(outputs["out_obj_ids"])
            locations = np.flatnonzero(ids == 1)
            if len(locations) != 1:
                report[view["name"]] = {
                    "valid": False,
                    "error": "대상 마스크를 찾지 못했습니다.",
                }
                return
            a = np.asarray(outputs["out_binary_masks"])[locations[0]].squeeze()
            if a.shape != (height, width):
                raise ValueError("마스크 출력 크기가 입력 사진과 다릅니다.")
            x, y = view["padding_xy"]
            w, h = view["size"]
            a = (a[y : y + h, x : x + w] > 0).astype(np.uint8) * 255
            path = output / (Path(view["name"]).stem + ".png")
            Image.fromarray(a).save(path)
            try:
                stats = validate_mask(path, (w, h))
                warnings = []
                if view["discontinuity"]:
                    warnings.append("촬영 시점의 간격이 큽니다. 마스크를 확인하세요.")
                if stats["coverage"] > 0.98:
                    warnings.append("마스크가 사진 대부분을 덮습니다.")
                report[view["name"]] = {
                    "valid": True,
                    **stats,
                    "warnings": warnings,
                    "object_id": 1,
                }
            except ValueError as exc:
                report[view["name"]] = {"valid": False, "error": str(exc)}
            atomic_json(output / "masks.json", report)
            print(
                json.dumps(
                    {
                        "frame": idx,
                        "name": view["name"],
                        "current": len(report),
                        "total": len(expected),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

        try:
            response = predictor.handle_request(
                dict(
                    type="add_prompt",
                    session_id=session,
                    frame_index=ref["frame_index"],
                    points=prompts,
                    point_labels=labels,
                    obj_id=1,
                )
            )
            save(response)
            if report[reference]["valid"] and not preview:
                for response in predictor.handle_stream_request(
                    dict(
                        type="propagate_in_video",
                        session_id=session,
                        start_frame_index=ref["frame_index"],
                        max_frame_num_to_track=radius,
                        force_tracker_propagation=True,
                    )
                ):
                    save(response)
            for view in expected:
                report.setdefault(
                    view["name"], {"valid": False, "error": "전파 결과가 없습니다."}
                )
            for previous, current in zip(frame_map, frame_map[1:]):
                a, b = report.get(previous["name"], {}), report.get(current["name"], {})
                if (
                    a.get("valid")
                    and b.get("valid")
                    and not 0.4 <= b["coverage"] / max(a["coverage"], 1e-8) <= 2.5
                ):
                    b["warnings"].append(
                        "인접 시점에서 마스크 면적이 크게 바뀌었습니다. 대상을 확인하세요."
                    )
            atomic_json(output / "masks.json", report)
        finally:
            predictor.handle_request(dict(type="close_session", session_id=session))
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    import os

    memory_fraction = os.environ.get("STUDIO_SAM_MEMORY_FRACTION")
    if memory_fraction is not None:
        import torch

        value = float(memory_fraction)
        if not 0 < value <= 1:
            raise ValueError("GPU 메모리 비율은 0보다 크고 1 이하여야 합니다.")
        torch.cuda.set_per_process_memory_fraction(value)
    segment(**request)
