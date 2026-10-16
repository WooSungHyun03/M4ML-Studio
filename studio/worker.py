"""Foreground scientific worker. API launches one child; CUDA jobs use an OS lock."""

import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import threading
import time

from studio.colmap import reconstruct, validate_scene, select_existing
from studio.doctor import ROOT, atomic_json, sha256
from studio.mesh import validate_mesh
from studio.process import run, Cancelled, failure_message
from studio.sam31 import validate_mask
from studio.store import Store, invalidate, now


def run_job(job_id):
    store = Store()
    job = store.job(job_id)
    project_id = job["project_id"]
    stage = job["stage"]
    p = store.get(project_id)
    root = store.path(project_id)
    request = json.loads(job["request"])
    cancel = threading.Event()
    if job.get("cancel_requested"):
        cancel.set()
    owner_pid = os.environ.get("STUDIO_OWNER_PID")
    owner_start = os.environ.get("STUDIO_OWNER_START")
    if owner_pid:

        def owner_monitor():
            while not cancel.wait(0.5):
                try:
                    if (
                        Path(f"/proc/{owner_pid}/stat").read_text().split()[21]
                        != owner_start
                    ):
                        cancel.set()
                        return
                except (OSError, IndexError):
                    cancel.set()
                    return

        threading.Thread(target=owner_monitor, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: cancel.set())
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    store.job_update(job_id, pid=os.getpid(), message="작업을 준비하고 있습니다.")
    output = root / "runs" / job_id
    output.mkdir(parents=True)
    log = root / "logs" / (job_id + ".log")
    lock = None
    try:
        if stage != "colmap":
            import hashlib

            locks = (
                Path(os.environ.get("XDG_RUNTIME_DIR", Path.home() / ".cache"))
                / "object-aware-studio-locks"
            )
            locks.mkdir(parents=True, exist_ok=True, mode=0o700)
            device_key = hashlib.sha256(
                str(request.get("gpu_uuid", request["gpu"])).encode()
            ).hexdigest()
            lock = (locks / (device_key + ".lock")).open("a")
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    store.job_update(
                        job_id,
                        message="선택한 GPU에서 앞선 작업이 끝나기를 기다립니다.",
                    )
                    if cancel.wait(0.5):
                        raise Cancelled("GPU 대기 중 취소되었습니다.")

        def progress(line):
            match = re.search(r"(\d+)/(\d+).*?Loss=([\d.eE+-]+)", line)
            if match:
                store.job_update(
                    job_id,
                    current=int(match[1]),
                    total=int(match[2]),
                    message=f"학습 손실 {match[3]}",
                )
            elif line.startswith('{"frame"'):
                item = json.loads(line)
                store.job_update(
                    job_id,
                    current=item["current"],
                    total=item["total"],
                    message="마스크를 생성하고 있습니다.",
                )

        env = os.environ.copy()
        env.update(
            CUDA_VISIBLE_DEVICES=str(request.get("gpu_uuid", request.get("gpu", 0))),
            OMP_NUM_THREADS="4",
            PYTHONUNBUFFERED="1",
        )

        def command(args, timeout=86400):
            run(
                [sys.executable, *args],
                log,
                cwd=ROOT,
                env=env,
                cancel=cancel,
                timeout=timeout,
                on_line=progress,
            )

        if stage == "colmap":
            if request.get("component") is not None:
                store.job_update(
                    job_id,
                    message="선택한 재구성 그룹의 렌즈 왜곡을 보정하고 있습니다.",
                )
                report = select_existing(
                    root / "input/original",
                    (root / p["scene"]).parent,
                    output / "colmap",
                    request["component"],
                    cancel=cancel,
                )
            else:
                report = reconstruct(
                    root / "input/original",
                    output / "colmap",
                    matching=request.get("matching", "exhaustive"),
                    cancel=cancel,
                    progress=lambda message: store.job_update(job_id, message=message),
                )
            scene = (output / "colmap/scene").relative_to(root).as_posix()

            def finish(doc):
                doc["scene"] = scene
                doc["colmap_report"] = report
                doc["masks"] = {}
                doc.pop("preview", None)
                doc.pop("prompt", None)
                doc["target_confirmed"] = False
                invalidate(doc, "colmap")
                doc["stages"].update(colmap="completed", sam="waiting_for_user")

            store.update(project_id, finish)
        elif stage in {"preview", "sam"}:
            store.job_update(
                job_id,
                message="SAM 3.1 가중치를 불러오고 등록 사진의 마스크를 계산하고 있습니다.",
            )
            scene = root / p["scene"]
            args = {
                "scene": str(scene),
                "checkpoint": request["checkpoint"],
                "reference": request["reference"],
                "points": request["points"],
                "labels": request["labels"],
                "output": str(output / "predictions"),
                "preview": stage == "preview",
                "radius": request.get("radius"),
            }
            atomic_json(output / "sam_request.json", args)
            command(["-m", "studio.sam31", str(output / "sam_request.json")])
            results = json.loads((output / "predictions/masks.json").read_text())

            def finish(doc):
                doc["prompt"] = {
                    k: request[k] for k in ("reference", "points", "labels")
                }
                if stage == "preview":
                    if not results[request["reference"]]["valid"]:
                        raise ValueError(
                            "대상 마스크가 비어 있습니다. 클릭 위치를 바꾸세요."
                        )
                    doc["preview"] = {
                        "path": str(
                            (
                                output
                                / "predictions"
                                / (Path(request["reference"]).stem + ".png")
                            ).relative_to(root)
                        ),
                        "reference": request["reference"],
                        "request": doc["prompt"],
                        "revision": doc["revision"],
                    }
                    doc["stages"]["sam"] = (
                        "completed" if doc["masks"] else "waiting_for_user"
                    )
                else:
                    for name, item in results.items():
                        # Reviewed data is preserved during prompt corrections/repropagation.
                        old = doc["masks"].get(name, {})
                        if old.get("status") in {"approved", "manual", "skipped"}:
                            continue
                        doc["masks"][name] = {
                            **item,
                            "status": "generated" if item["valid"] else "invalid",
                            "path": str(
                                (
                                    output / "predictions" / (Path(name).stem + ".png")
                                ).relative_to(root)
                            ),
                            "generated_path": str(
                                (
                                    output / "predictions" / (Path(name).stem + ".png")
                                ).relative_to(root)
                            ),
                        }
                    doc["target_confirmed"] = True
                    invalidate(doc, "sam")
                    doc.pop("preview", None)
                    doc["stages"].update(sam="completed", review="review_required")

            store.update(project_id, finish)
        elif stage == "train":
            store.job_update(
                job_id,
                message="학습 사진·마스크를 검사하고 원본 Object-Aware 학습을 준비하고 있습니다.",
            )
            scene = root / p["scene"]
            names = validate_scene(scene)
            mask_dir = scene / "mask"
            mask_dir.mkdir(exist_ok=True)
            fingerprints = {}
            from PIL import Image

            for name in names:
                item = p["masks"][name]
                if item["status"] not in {"approved", "manual", "skipped"}:
                    raise ValueError("마스크 검토 또는 명시적 생략이 필요합니다.")
                with Image.open(scene / "images" / name) as image:
                    stats = validate_mask(root / item["path"], image.size)
                if stats["sha256"] != item["sha256"]:
                    raise ValueError("마스크 파일이 변경되었습니다. 다시 확인하세요.")
                shutil.copyfile(
                    root / item["path"], mask_dir / (Path(name).stem + ".png")
                )
                fingerprints[name] = stats["sha256"]
            atomic_json(
                output / "input_fingerprint.json",
                {
                    "masks": fingerprints,
                    "revision": p["revision"],
                    "iterations": request["iterations"],
                },
            )
            command(
                [
                    "-c",
                    "import sys,torch; print('Runtime:',sys.executable,'Torch:',torch.__version__,'실제 선택 GPU:',torch.cuda.get_device_name(0), 'CUDA:',torch.version.cuda,torch.cuda.get_device_properties(0)); assert torch.cuda.is_available(); assert torch.cuda.current_device()==0",
                ]
            )
            training = output / "training"
            checkpoints = sorted(
                set(
                    [
                        *range(5000, request["iterations"] + 1, 5000),
                        request["iterations"],
                    ]
                )
            )
            command(
                [
                    "train.py",
                    "-s",
                    str(scene),
                    "-m",
                    str(training),
                    "--iterations",
                    str(request["iterations"]),
                    "--checkpoint_iterations",
                    *[str(iteration) for iteration in checkpoints],
                    "--port",
                    "0",
                    "--resolution",
                    str(request.get("resolution", -1)),
                ]
            )
            from plyfile import PlyData
            import numpy as np

            ply = (
                training
                / "point_cloud"
                / f"iteration_{request['iterations']}"
                / "point_cloud.ply"
            )
            vertices = PlyData.read(ply)["vertex"]
            if not len(vertices) or not all(
                np.isfinite(vertices[k]).all() for k in ("x", "y", "z")
            ):
                raise ValueError("학습 결과에 유효한 가우시안이 없습니다.")

            def finish(doc):
                invalidate(doc, "train")
                doc["training"] = {
                    "path": str(training.relative_to(root)),
                    "iterations": request["iterations"],
                    "revision": doc["revision"],
                    "gaussians": len(vertices),
                    "gpu": request["gpu"],
                    "ply_sha256": sha256(ply),
                }
                doc["stages"]["train"] = "completed"

            store.update(project_id, finish)
        elif stage == "mesh":
            store.job_update(
                job_id,
                message="학습 결과를 렌더링하고 TSDF 표면 메시를 추출하고 있습니다.",
            )
            training = root / p["training"]["path"]
            command(
                [
                    "render.py",
                    "-s",
                    str(root / p["scene"]),
                    "-m",
                    str(training),
                    "--skip_train",
                    "--skip_test",
                    "--mesh_res",
                    str(request.get("mesh_res", 1024)),
                ]
            )
            ply = (
                training
                / "train"
                / f"ours_{p['training']['iterations']}"
                / "fuse_post.ply"
            )
            report = validate_mesh(ply, output / "mesh")
            shutil.copyfile(ply, output / "mesh/fuse_post.ply")

            def finish(doc):
                doc["mesh"] = {
                    "path": str((output / "mesh").relative_to(root)),
                    **report,
                }
                doc["stages"]["mesh"] = "completed"

            store.update(project_id, finish)
        else:
            raise ValueError("알 수 없는 작업입니다.")
        if cancel.is_set():
            raise Cancelled("작업이 취소되었습니다.")
        store.job_update(
            job_id,
            state="completed",
            ended=now(),
            message="결과 파일 검증을 완료했습니다.",
            exit_code=0,
        )
    except BaseException as exc:
        import traceback

        with log.open("a") as stream:
            traceback.print_exc(file=stream)
        state = "cancelled" if isinstance(exc, Cancelled) else "failed"
        message = failure_message(log, exc)
        store.job_update(job_id, state=state, ended=now(), message=message, exit_code=1)
        store.update(
            project_id,
            lambda doc: doc["stages"].update(
                {"sam" if stage == "preview" else stage: state}
            ),
        )
        if stage == "colmap" and (output / "colmap/report.json").is_file():
            report = json.loads((output / "colmap/report.json").read_text())
            store.update(project_id, lambda doc: doc.update(colmap_report=report))
        raise
    finally:
        if lock:
            lock.close()
    if stage == "train" and store.job(job_id)["state"] == "completed":
        # Training was explicitly approved at the API gate. Mesh extraction is
        # the next unattended stage and starts only after CUDA lock release.
        from studio.dispatch import launch

        launch(
            store,
            project_id,
            "mesh",
            {
                "gpu": request["gpu"],
                "gpu_uuid": request.get("gpu_uuid", str(request["gpu"])),
                "mesh_res": request.get("mesh_res", 1024),
            },
        )


if __name__ == "__main__":
    run_job(sys.argv[1])
