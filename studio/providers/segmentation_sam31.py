"""Object selection / mask propagation provider backed by the official SAM 3.1 model."""

from __future__ import annotations

import json
from pathlib import Path

from studio.doctor import ROOT, atomic_json
from studio.providers.base import SegmentationProvider

DEFAULT_CHECKPOINT = ROOT / "models/sam3.1/sam3.1_multiplex.pt"


class Sam31SegmentationProvider(SegmentationProvider):
    key = "sam31"
    display_name = "SAM 3.1 (Meta, multiplex video predictor)"

    def checkpoint(self) -> Path:
        from studio.config import checkpoint_path

        import os

        configured = os.environ.get("STUDIO_SAM_CHECKPOINT") or self.options.get("checkpoint")
        return Path(configured).expanduser().resolve() if configured else checkpoint_path()

    def info(self):
        base = super().info()
        ckpt = self.checkpoint()
        base.update(
            checkpoint=str(ckpt),
            checkpoint_present=ckpt.is_file(),
            checkpoint_bytes=ckpt.stat().st_size if ckpt.is_file() else None,
            upstream="https://github.com/facebookresearch/sam3",
            upstream_revision="7f473cfd983d5eb43040ff608f66bff0d7bdcb53 (+3 compatibility patches, patches/sam3)",
            license="SAM License (see licenses/); checkpoint terms reviewed separately",
            runtime="PyTorch 2.5.1 + CUDA 11.8 (shared with reconstruction)",
        )
        verified = ROOT / "evidence/sam31-checkpoint.json"
        if verified.is_file():
            try:
                data = json.loads(verified.read_text())
                base["checkpoint_sha256"] = data.get("sha256")
                base["checkpoint_tensors"] = data.get("tensor_count") or len(data.get("tensors", {}))
            except ValueError:
                pass
        return base

    def _run(self, ctx, request, preview):
        if not self.checkpoint().is_file():
            raise ValueError(
                "객체 선택 모델 파일을 찾을 수 없습니다. 설정 › 고급 정보에서 경로를 확인하세요."
            )
        args = {
            "scene": request["scene"],
            "checkpoint": str(self.checkpoint()),
            "reference": request["reference"],
            "points": request["points"],
            "labels": request["labels"],
            "output": str(Path(request["output"])),
            "preview": preview,
            "radius": request.get("radius"),
            "parameters": request.get("parameters", {}),
        }
        req = Path(request["output"]).parent / (
            "predict_request.json" if preview else "propagate_request.json"
        )
        atomic_json(req, args)
        ctx.python(["-m", "studio.sam31", str(req)])
        return json.loads((Path(request["output"]) / "masks.json").read_text())

    def predict(self, ctx, request):
        return self._run(ctx, request, preview=True)

    def propagate(self, ctx, request):
        return self._run(ctx, request, preview=False)

    def session_command(self):
        return ["-m", "studio.sam31_session", "--checkpoint", str(self.checkpoint())]
