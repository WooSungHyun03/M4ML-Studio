"""Persistent interactive object-selection process (official SAM 3.1, model kept loaded).

Why: starting a fresh process per click re-loads the 3.5 GB checkpoint (~20 s per click).
This process loads and verifies the model once, then answers each prompt in well under a
second. It is owned by the API process (see ``studio/segmentation_session.py``), runs on
exactly one GPU (CUDA_VISIBLE_DEVICES), and exits when stdin closes, on ``close``, or
when the owning server disappears.

Protocol: one JSON object per line on stdin; one JSON object per line on stdout.
  → {"op":"predict","id":N,"image":path,"points":[[x,y],...],"labels":[1,0,...],"output":png}
  ← {"id":N,"ok":true,"result":{area,coverage,sha256,size,seconds}}  |  {"id":N,"ok":false,"error":...}
Points are pixel coordinates of the given (undistorted, registered) image.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def watch_owner():
    pid, start = os.environ.get("STUDIO_OWNER_PID"), os.environ.get("STUDIO_OWNER_START")
    if not pid:
        return

    def loop():
        while True:
            time.sleep(1)
            try:
                if Path(f"/proc/{pid}/stat").read_text().split()[21] != start:
                    os._exit(0)
            except (OSError, IndexError):
                os._exit(0)

    threading.Thread(target=loop, daemon=True).start()


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    a = ap.parse_args()
    watch_owner()
    # Keep protocol stdout clean: library logging goes to stderr (captured into a log file).
    real_stdout = sys.stdout
    sys.stdout = sys.stderr
    started = time.monotonic()
    import numpy as np
    from PIL import Image
    import torch
    from sam3.model_builder import build_sam3_multiplex_video_predictor
    from studio.sam31 import validate_mask

    if not torch.cuda.is_available():
        sys.stdout = real_stdout
        emit({"ready": False, "error": "GPU를 사용할 수 없습니다."})
        return 1
    fraction = os.environ.get("STUDIO_SAM_MEMORY_FRACTION")
    if fraction:
        torch.cuda.set_per_process_memory_fraction(float(fraction))
    checkpoint = Path(a.checkpoint)
    predictor = build_sam3_multiplex_video_predictor(
        checkpoint_path=str(checkpoint.resolve()),
        use_fa3=False,
        use_rope_real=False,
        compile=False,
        warm_up=False,
        async_loading_frames=False,
    )
    state = torch.load(checkpoint, weights_only=True, map_location="cpu", mmap=True)
    state = state.get("model", state)
    actual = predictor.model.state_dict()
    if set(state) != set(actual) or any(
        state[k].shape != actual[k].shape for k in state
    ):
        sys.stdout = real_stdout
        emit(
            {
                "ready": False,
                "error": "객체 선택 모델 파일이 공식 모델 구조와 일치하지 않습니다.",
            }
        )
        return 1
    del state, actual
    sys.stdout = real_stdout
    emit(
        {
            "ready": True,
            "seconds": round(time.monotonic() - started, 2),
            "device": torch.cuda.get_device_name(0),
        }
    )

    session_dir = tempfile.TemporaryDirectory(prefix="m4ml-sam-session-")
    current = {"image": None, "mtime": None, "session": None, "size": None}

    def open_frame(image_path: Path, offload=True):
        key = (str(image_path), (image_path.stat().st_mtime, offload))
        if current["session"] and (current["image"], current["mtime"]) == key:
            predictor.handle_request(
                dict(type="reset_session", session_id=current["session"])
            )
            return
        if current["session"]:
            predictor.handle_request(
                dict(type="close_session", session_id=current["session"])
            )
            current["session"] = None
        frames = Path(session_dir.name) / "frames"
        frames.mkdir(exist_ok=True)
        for old in frames.iterdir():
            old.unlink()
        with Image.open(image_path) as im:
            rgb = im.convert("RGB")
            current["size"] = rgb.size
            rgb.save(frames / "000000.png")
        sys.stdout = sys.stderr
        try:
            current["session"] = predictor.handle_request(
                dict(
                    type="start_session",
                    resource_path=str(frames),
                    offload_video_to_cpu=offload,
                )
            )["session_id"]
        finally:
            sys.stdout = real_stdout
        current["image"], current["mtime"] = key

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except ValueError:
            emit({"ok": False, "error": "잘못된 요청"})
            continue
        if req.get("op") == "close":
            break
        if req.get("op") != "predict":
            emit({"id": req.get("id"), "ok": False, "error": "지원하지 않는 요청"})
            continue
        t0 = time.monotonic()
        try:
            image = Path(req["image"])
            points, labels = req["points"], req["labels"]
            if (
                not points
                or len(points) != len(labels)
                or 1 not in labels
                or any(l not in (0, 1) for l in labels)
            ):
                raise ValueError("대상에 포함할 점을 한 개 이상 선택하세요.")
            from studio.task_settings import validate

            params = validate("segmentation", req.get("parameters", {}))
            predictor.model.fill_hole_area = params["fill_hole_area"]
            predictor.model.sprinkle_removal_area = params["sprinkle_removal_area"]
            open_frame(image, params["offload_video_to_cpu"])
            w, h = current["size"]
            if any(not (0 <= x < w and 0 <= y < h) for x, y in points):
                raise ValueError("클릭 좌표가 사진 밖에 있습니다.")
            sys.stdout = sys.stderr
            try:
                response = predictor.handle_request(
                    dict(
                        type="add_prompt",
                        session_id=current["session"],
                        frame_index=0,
                        points=[[x / w, y / h] for x, y in points],
                        point_labels=labels,
                        obj_id=1,
                    )
                )
            finally:
                sys.stdout = real_stdout
            outputs = response["outputs"]
            ids = np.asarray(outputs["out_obj_ids"])
            where = np.flatnonzero(ids == 1)
            if len(where) != 1:
                raise ValueError(
                    "대상 마스크를 찾지 못했습니다. 다른 위치를 클릭하세요."
                )
            mask = np.asarray(outputs["out_binary_masks"])[where[0]].squeeze()
            if mask.shape != (h, w):
                raise ValueError("마스크 크기가 사진과 다릅니다.")
            out = Path(req["output"])
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp.png")
            Image.fromarray(((mask > 0).astype(np.uint8) * 255)).save(tmp)
            os.replace(tmp, out)
            stats = validate_mask(out, (w, h))
            emit(
                {
                    "id": req.get("id"),
                    "ok": True,
                    "result": {
                        **stats,
                        "applied_settings": params,
                        "model_pid": os.getpid(),
                        "seconds": round(time.monotonic() - t0, 3),
                    },
                }
            )
        except torch.OutOfMemoryError:
            torch.cuda.empty_cache()
            emit(
                {
                    "id": req.get("id"),
                    "ok": False,
                    "oom": True,
                    "error": "GPU 메모리가 부족합니다. 다른 GPU 작업을 종료한 뒤 다시 클릭하세요.",
                }
            )
        except Exception as exc:  # noqa: BLE001 — reported to the user as text
            emit({"id": req.get("id"), "ok": False, "error": str(exc)})
    if current["session"]:
        predictor.handle_request(
            dict(type="close_session", session_id=current["session"])
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
