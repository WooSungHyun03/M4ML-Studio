"""Genuine SAM3.1 positive/negative prompting and three-frame GPU propagation.

Use a contiguous source video sequence. This compatibility test does NOT prove
arbitrary unordered multi-view accuracy, COLMAP registration, or product E2E.
"""

import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studio.doctor import atomic_json, sha256


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--frames", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--positive", type=float, nargs=2, required=True, metavar=("X", "Y"))
    p.add_argument("--negative", type=float, nargs=2, required=True, metavar=("X", "Y"))
    args = p.parse_args()
    import numpy as np
    from PIL import Image
    import torch

    print("RUNTIME", sys.executable, torch.__version__, torch.version.cuda, flush=True)
    assert torch.__version__.split("+")[0] == "2.5.1" and torch.version.cuda == "11.8"
    print("GPU", torch.cuda.get_device_name(0), flush=True)
    from sam3.model_builder import build_sam3_multiplex_video_predictor

    names = sorted(
        (
            f
            for f in args.frames.iterdir()
            if f.suffix.lower() in {".png", ".jpg", ".jpeg"}
        ),
        key=lambda f: int(f.stem),
    )
    assert len(names) >= 3
    width, height = Image.open(names[0]).size
    assert all(Image.open(f).size == (width, height) for f in names)
    args.output.mkdir(parents=True, exist_ok=True)
    frame_map = [
        {"frame_index": i, "path": str(path.resolve()), "sha256": sha256(path)}
        for i, path in enumerate(names)
    ]
    atomic_json(args.output / "frames.json", frame_map)
    started = time.monotonic()
    predictor = build_sam3_multiplex_video_predictor(
        checkpoint_path=str(args.checkpoint.resolve()),
        use_fa3=False,
        use_rope_real=False,
        compile=False,
        warm_up=False,
        async_loading_frames=False,
    )
    print(
        "MODEL",
        type(predictor).__name__,
        "loaded_seconds",
        time.monotonic() - started,
        flush=True,
    )
    # Upstream merged checkpoint loader uses strict=False: independently require
    # complete final model key/shape equality, never accept random missing weights.
    state = torch.load(
        args.checkpoint, map_location="cpu", weights_only=True, mmap=True
    )
    state = state.get("model", state)
    if any(k.startswith(("sam3_model.", "sam2_predictor.")) for k in state):
        state = {
            k.replace("sam3_model.", "detector.", 1).replace(
                "sam2_predictor.", "tracker.", 1
            ): v
            for k, v in state.items()
        }
    model_state = predictor.model.state_dict()
    assert set(model_state) == set(state), {
        "missing": sorted(set(model_state) - set(state)),
        "unexpected": sorted(set(state) - set(model_state)),
    }
    assert all(model_state[k].shape == v.shape for k, v in state.items())
    print("PASS complete checkpoint key/shape match", len(state), flush=True)
    del state, model_state
    session = predictor.handle_request(
        dict(
            type="start_session",
            resource_path=str(args.frames.resolve()),
            offload_video_to_cpu=True,
        )
    )["session_id"]
    records = []

    def persist(response, kind):
        out = response["outputs"]
        idx = response["frame_index"]
        ids = np.asarray(out["out_obj_ids"])
        masks = out["out_binary_masks"]
        if isinstance(masks, torch.Tensor):
            masks = masks.detach().cpu().numpy()
        masks = np.asarray(masks)
        positions = np.flatnonzero(ids == 1)
        assert len(positions) == 1, {"index": idx, "object_ids": ids.tolist()}
        mask = masks[positions[0]].squeeze()
        assert mask.shape == (height, width), mask.shape
        binary = (mask > 0).astype(np.uint8) * 255
        assert 0 < np.count_nonzero(binary) < width * height
        Image.fromarray(binary, mode="L").save(args.output / f"{kind}_{idx:06d}.png")
        record = {
            "kind": kind,
            "frame_index": int(idx),
            "object_id": 1,
            "area": int(np.count_nonzero(binary)),
            "shape": list(binary.shape),
        }
        records.append(record)
        print("MASK", record, flush=True)

    try:
        points = [[x / width, y / height] for x, y in (args.positive, args.negative)]
        for x, y in points:
            assert 0 <= x < 1 and 0 <= y < 1
        positive = predictor.handle_request(
            dict(
                type="add_prompt",
                session_id=session,
                frame_index=0,
                points=points[:1],
                point_labels=[1],
                obj_id=1,
            )
        )
        persist(positive, "positive")
        refined = predictor.handle_request(
            dict(
                type="add_prompt",
                session_id=session,
                frame_index=0,
                points=points,
                point_labels=[1, 0],
                obj_id=1,
            )
        )
        persist(refined, "positive_negative")
        # A point-only session has no detector previous_stages_out. The official
        # API needs the known clicked frame as explicit propagation start.
        for response in predictor.handle_stream_request(
            dict(type="propagate_in_video", session_id=session, start_frame_index=0)
        ):
            persist(response, "propagation")
        assert {r["frame_index"] for r in records if r["kind"] == "propagation"} == set(
            range(len(names))
        )
        atomic_json(
            args.output / "result.json",
            {
                "status": "PASS",
                "python": sys.executable,
                "torch": torch.__version__,
                "cuda": torch.version.cuda,
                "gpu": torch.cuda.get_device_name(0),
                "checkpoint_sha256": sha256(args.checkpoint),
                "model": type(predictor.model).__name__,
                "points_pixels": [args.positive, args.negative],
                "labels": [1, 0],
                "records": records,
                "seconds": time.monotonic() - started,
            },
        )
        print("PASS SAM3.1 positive/negative points and real propagation", flush=True)
    finally:
        predictor.handle_request(dict(type="close_session", session_id=session))


if __name__ == "__main__":
    main()
