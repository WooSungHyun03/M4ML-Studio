"""Safely inventory tensor data; never deserialize arbitrary checkpoint Python objects."""

import argparse
from collections import Counter
from pathlib import Path

from studio.doctor import atomic_json, sha256


def inspect_checkpoint(path):
    import torch

    state = torch.load(path, map_location="cpu", weights_only=True, mmap=True)
    if isinstance(state, dict) and isinstance(state.get("model"), dict):
        state = state["model"]
    if not isinstance(state, dict) or not state:
        raise ValueError("체크포인트에 텐서 사전이 없습니다.")
    if not all(
        isinstance(k, str) and isinstance(v, torch.Tensor) for k, v in state.items()
    ):
        raise ValueError("예상하지 못한 체크포인트 형식입니다.")
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "torch": torch.__version__,
        "load": "weights_only=True, mmap=True, CPU",
        "tensor_count": len(state),
        "elements": sum(v.numel() for v in state.values()),
        "prefix_counts": dict(Counter(k.split(".")[0] for k in state)),
        "dtypes": dict(Counter(str(v.dtype) for v in state.values())),
        "tensors": {k: list(v.shape) for k, v in state.items()},
        "identity": "tensor inventory only; official model key/shape matching and real inference required",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("checkpoint", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report = inspect_checkpoint(args.checkpoint)
    atomic_json(args.output, report)
    print({k: v for k, v in report.items() if k != "tensors"})


if __name__ == "__main__":
    main()
