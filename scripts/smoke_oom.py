"""Real original-train CUDA OOM using a tiny per-process allocator quota.

Does not exhaust global VRAM, change upstream train.py, or replace inference.
"""

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio.doctor import atomic_json
from studio.process import run, failure_message
from studio.store import Store, now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    store = Store(args.output / "state")
    project = store.create("실제 CUDA OOM 부정 경로")
    job_id = store.new_job(
        project["id"], "train", {"test_only_cuda_memory_fraction": 0.002}
    )
    log = args.output / "original-train-oom.log"
    wrapper = "import torch,sys,runpy; print('Actual GPU:',torch.cuda.get_device_name(0)); torch.cuda.set_per_process_memory_fraction(0.002,0); print('Test-only per-process CUDA allocator quota: 0.002'); sys.argv=['train.py',*sys.argv[1:]]; runpy.run_path('train.py',run_name='__main__')"
    env = os.environ.copy()
    env.update(CUDA_VISIBLE_DEVICES="0", OMP_NUM_THREADS="4", PYTHONUNBUFFERED="1")
    try:
        run(
            [
                sys.executable,
                "-c",
                wrapper,
                "-s",
                args.scene.resolve(),
                "-m",
                (args.output / "training").resolve(),
                "--iterations",
                "100",
                "--port",
                "0",
            ],
            log,
            cwd=ROOT,
            env=env,
            timeout=120,
        )
    except RuntimeError as exc:
        assert "out of memory" in log.read_text().lower(), log.read_text()[-2000:]
        message = failure_message(log, exc)
        assert "GPU 메모리" in message
        store.job_update(
            job_id, state="failed", ended=now(), message=message, exit_code=1
        )
        store.update(project["id"], lambda p: p["stages"].update(train="failed"))
        assert not (
            args.output / "training/point_cloud/iteration_100/point_cloud.ply"
        ).exists()
        atomic_json(
            args.output / "result.json",
            {
                "status": "PASS",
                "test": "real original train CUDA allocator OOM",
                "quota": 0.002,
                "job": store.job(job_id),
                "no_completed_training_artifact": True,
            },
        )
        print(
            "PASS actual CUDA OOM recorded failed with Korean guidance; no completed training artifact."
        )
    else:
        raise AssertionError("Quota did not cause expected real CUDA OOM")


if __name__ == "__main__":
    main()
