"""3D reconstruction provider: the ORIGINAL Object-Aware Loss / 2DGS ``train.py``.

The scientific code is invoked unchanged. Resume uses the original ``--start_checkpoint``
argument with a checkpoint written by the same run. Checkpoints are written every
``checkpoint_every`` iterations so a pause loses at most that many iterations; only the
newest ``keep_checkpoints`` intermediate checkpoints are kept to bound disk use (the
original code itself never deletes anything; pruning happens here, outside it).
"""

from __future__ import annotations

from pathlib import Path
import re
import threading

from studio.doctor import ROOT
from studio.providers.base import TrainingProgress, TrainingProvider

PROGRESS = re.compile(r"(\d+)/(\d+).*?Loss=([\d.eE+-]+)")


def list_checkpoints(model: Path):
    out = []
    for path in Path(model).glob("chkpnt*.pth"):
        m = re.fullmatch(r"chkpnt(\d+)\.pth", path.name)
        if m:
            out.append(int(m[1]))
    return sorted(out)


class ObjectAwareTrainingProvider(TrainingProvider):
    key = "object_aware_2dgs"
    display_name = "Object-Aware Loss · 2D Gaussian Splatting (original train.py)"

    def info(self):
        base = super().info()
        base.update(
            source="https://github.com/WooSungHyun03/object-aware-loss",
            paper="https://www.mdpi.com/2227-7390/14/17/3221",
            entrypoint=str(ROOT / "train.py"),
            losses=["Masked L1", "Alpha Polarization", "ObjectMark Polarization", "ObjectMark pruning", "2DGS normal/distortion"],
            runtime="PyTorch 2.5.1 + CUDA 11.8, native diff-surfel-rasterization / simple-knn",
            license="Gaussian-Splatting License — non-commercial research/evaluation only (licenses/)",
            default_iterations=self.options.get("iterations", 30000),
        )
        return base

    def parse_progress(self, line):
        m = PROGRESS.search(line)
        if m:
            return TrainingProgress(int(m[1]), int(m[2]), float(m[3]))
        return None

    def checkpoints(self, model):
        return list_checkpoints(model)

    def train(self, ctx, scene, model, request):
        iterations = int(request["iterations"])
        every = int(
            request.get("parameters", {}).get(
                "checkpoint_every", self.options.get("checkpoint_every", 2500)
            )
        )
        keep = int(self.options.get("keep_checkpoints", 2))
        marks = sorted({*range(every, iterations, every), iterations})
        argv = [
            "train.py",
            "-s",
            str(scene),
            "-m",
            str(model),
            "--iterations",
            str(iterations),
            "--checkpoint_iterations",
            *map(str, marks),
            "--port",
            "0",
            "--resolution",
            str(request.get("resolution", -1)),
        ]
        from studio.task_settings import definitions

        supported = {f["native"] for f in self.task_settings_schema()} - {
            "iterations",
            "resolution",
            "checkpoint_every",
        }
        for key, value in request.get("parameters", {}).items():
            if key not in supported:
                continue
            if type(value) is bool:
                if value:
                    argv.append("--" + key)
            else:
                argv += ["--" + key, str(value)]
        resumed = None
        if request.get("resume_iteration"):
            resumed = int(request["resume_iteration"])
            checkpoint = Path(model) / f"chkpnt{resumed}.pth"
            if not checkpoint.is_file():
                raise ValueError("이어서 학습할 저장 지점을 찾을 수 없습니다.")
            if resumed >= iterations:
                raise ValueError("이미 목표 반복 횟수까지 학습했습니다.")
            argv += ["--start_checkpoint", str(checkpoint)]
        ctx.progress("학습 실행 설정: " + str(request.get("parameters", {})))
        # Device sanity check in the SAME env as training; fails loudly if CUDA is not used.
        ctx.python(
            [
                "-c",
                "import torch,sys; assert torch.cuda.is_available(), 'CUDA unavailable';"
                "print('device:', torch.cuda.get_device_name(0), '| torch', torch.__version__, '| cuda', torch.version.cuda)",
            ],
            timeout=300,
        )

        existing_marks = set(list_checkpoints(model))
        stop = threading.Event()

        def prune():
            while not stop.wait(5):
                found = list_checkpoints(model)
                for old in found[:-keep]:
                    if old != iterations and old not in existing_marks:
                        (Path(model) / f"chkpnt{old}.pth").unlink(missing_ok=True)

        pruner = threading.Thread(target=prune, daemon=True)
        pruner.start()
        try:
            ctx.python(argv)
        finally:
            stop.set()
            pruner.join(timeout=10)
        return {
            "iterations": iterations,
            "resumed_from": resumed,
            "checkpoints": list_checkpoints(model),
        }
