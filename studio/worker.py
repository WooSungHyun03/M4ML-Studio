"""Foreground pipeline worker: one child process per job, engines behind providers.

The worker owns orchestration only — stage state, invalidation, GPU device lock,
cancellation and durable job records. All engine-specific work goes through the
capability providers configured in ``studio.engines`` (camera, segmentation,
training, mesh, export).
"""

import json
import os
from pathlib import Path
import shutil
import signal
import sys
import threading

from studio import gpu_lock
from studio.doctor import ROOT, atomic_json, sha256
from studio.engines import provider
from studio.process import Cancelled, failure_message
from studio.providers.base import JobContext
from studio.sam31 import validate_mask
from studio.store import Store, invalidate, now
from studio.progress import ProgressReporter


def _owner_monitor(cancel):
    owner_pid = os.environ.get("STUDIO_OWNER_PID")
    owner_start = os.environ.get("STUDIO_OWNER_START")
    if not owner_pid:
        return

    def loop():
        while not cancel.wait(0.5):
            try:
                if Path(f"/proc/{owner_pid}/stat").read_text().split()[21] != owner_start:
                    cancel.set()
                    return
            except (OSError, IndexError):
                cancel.set()
                return

    threading.Thread(target=loop, daemon=True).start()


def _acquire_gpu(store, job_id, device, cancel):
    while True:
        handle = gpu_lock.try_acquire(device)
        if handle:
            return handle
        store.job_update(job_id, message="선택한 GPU에서 앞선 작업이 끝나기를 기다립니다.")
        if cancel.wait(0.5):
            raise Cancelled("GPU 대기 중 취소되었습니다.")


def _mask_record(root, output, name, item):
    path = str((output / "predictions" / (Path(name).stem + ".png")).relative_to(root))
    return {**item, "status": "generated" if item["valid"] else "invalid", "path": path, "generated_path": path}


def run_job(job_id):
    store = Store()
    job = store.job(job_id)
    project_id, stage = job["project_id"], job["stage"]
    p = store.get(project_id)
    root = store.path(project_id)
    request = json.loads(job["request"])
    cancel = threading.Event()
    if job.get("cancel_requested"):
        cancel.set()
    _owner_monitor(cancel)
    signal.signal(signal.SIGTERM, lambda *_: cancel.set())
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    store.job_update(job_id, pid=os.getpid(), message="작업을 준비하고 있습니다.")
    output = root / "runs" / job_id
    output.mkdir(parents=True)
    atomic_json(output / "execution_request.json",request)
    atomic_json(
        output / "execution_settings.json", request.get("settings_snapshot", {})
    )
    log = root / "logs" / (job_id + ".log")
    lock = None
    capability = {
        "colmap": "camera",
        "preview": "segmentation",
        "sam": "segmentation",
        "train": "training",
        "mesh": "mesh",
    }.get(stage)
    try:
        if capability is None:
            raise ValueError("알 수 없는 작업입니다.")
        if cancel.is_set():
            # A cancel recorded before the worker started wins over any start-up error
            # (e.g. a missing GPU engine): the user asked for the job not to run.
            raise Cancelled("시작 전에 취소되었습니다.")
        engine = provider(capability)
        device = str(request.get("gpu_uuid", request.get("gpu", 0)))
        if engine.requires_gpu(request):
            lock = _acquire_gpu(store, job_id, device, cancel)

        progress = ProgressReporter(store, job_id)

        offset = {"iteration": 0, "total": None}  # set when resuming from a checkpoint

        def on_line(line):
            parsed = provider("training").parse_progress(line) if stage == "train" else None
            if parsed:
                # tqdm restarts at 0 after --start_checkpoint; report absolute iterations.
                progress(current=parsed.iteration + offset["iteration"],
                                 total=offset["total"] or parsed.total,
                                 message=f"3D 재구성 학습 중 · 손실 {parsed.loss:.5f}")
            elif line.startswith('{"frame"'):
                item = json.loads(line)
                store.job_update(job_id, current=item["current"], total=item["total"],
                                 message="마스크를 생성하고 있습니다.")

        env = os.environ.copy()
        env.update(
            CUDA_VISIBLE_DEVICES=device, OMP_NUM_THREADS="4", PYTHONUNBUFFERED="1"
        )
        ctx = JobContext(
            root=root,
            output=output,
            log=log,
            env=env,
            cancel=cancel,
            progress=progress,
            cwd=ROOT,
            on_line=on_line,
        )

        if stage == "colmap":
            if request.get("component") is not None:
                progress("선택한 재구성 그룹의 렌즈 왜곡을 보정하고 있습니다.")
                report = engine.select_component(
                    ctx,
                    root / "input/original",
                    (root / p["scene"]).parent,
                    output / "colmap",
                    request["component"],
                )
            else:
                report = engine.reconstruct(
                    ctx, root / "input/original", output / "colmap", request
                )
            scene = (output / "colmap/scene").relative_to(root).as_posix()

            def finish(doc):
                doc["scene"] = scene
                doc["colmap_report"] = report
                doc["masks"] = {}
                doc.pop("preview", None)
                doc.pop("prompt", None)
                doc.pop("training_partial", None)
                doc.pop("active_gaussian_artifact", None)
                doc["target_confirmed"] = False
                invalidate(doc, "colmap")
                doc["stages"].update(colmap="completed", sam="waiting_for_user")

            store.update(project_id, finish)

        elif stage in {"preview", "sam"}:
            progress(
                "객체 선택 모델을 불러오고 등록 사진의 마스크를 계산하고 있습니다."
            )
            seg_request = {
                "scene": str(root / p["scene"]),
                "reference": request["reference"],
                "points": request["points"],
                "labels": request["labels"],
                "output": str(output / "predictions"),
                "radius": request.get("radius"),
                "parameters": request.get("parameters", {}),
            }
            results = (engine.predict if stage == "preview" else engine.propagate)(
                ctx, seg_request
            )

            def finish(doc):
                if stage == "preview" and request.get("session_id"):
                    from studio.live_prompt import matches

                    if not matches(doc, request) or doc.get("live_prompt", {}).get("status") != "pending":
                        raise Cancelled("이전 클릭 결과는 버리고 최신 클릭을 처리합니다.")
                    doc["live_prompt"].update(status="ready")
                doc["prompt"] = {k: request[k] for k in ("reference", "points", "labels")}
                if stage == "preview":
                    if not results[request["reference"]]["valid"]:
                        raise ValueError("대상 마스크가 비어 있습니다. 클릭 위치를 바꾸세요.")
                    doc["preview"] = {
                        "path": str((output / "predictions" / (Path(request["reference"]).stem + ".png")).relative_to(root)),
                        "reference": request["reference"],
                        "request": doc["prompt"],
                        "revision": doc["revision"],
                        "session_id": request.get("session_id"),
                        "prompt_revision": request.get("prompt_revision"),
                        "project_id": project_id,
                        "frame_id": request["reference"],
                    }
                    doc["stages"]["sam"] = "completed" if doc["masks"] else "waiting_for_user"
                else:
                    for name, item in results.items():
                        # Reviewed data is preserved during prompt corrections/repropagation.
                        if doc["masks"].get(name, {}).get("status") in {"approved", "manual", "skipped"}:
                            continue
                        doc["masks"][name] = _mask_record(root, output, name, item)
                    doc["target_confirmed"] = True
                    invalidate(doc, "sam")
                    doc.pop("preview", None)
                    doc["stages"].update(sam="completed", review="review_required")

            store.update(project_id, finish)

        elif stage == "train":
            progress("학습 사진과 마스크를 검사하고 3D 재구성을 준비하고 있습니다.")
            scene = root / p["scene"]
            names = provider("camera").validate_scene(scene)
            fingerprints = {}
            from PIL import Image

            mask_dir = scene / "mask"
            mask_dir.mkdir(exist_ok=True)
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
            from studio.artifacts import dataset_identity, require_resume_identity

            fingerprint = {
                "dataset": dataset_identity(scene, names),
                "masks": fingerprints,
                "scene": p["scene"],
                "iterations": request["iterations"],
                "resolution": request.get("resolution", -1),
                "settings": request.get("settings_snapshot"),
            }
            partial = p.get("training_partial")
            if request.get("resume"):
                require_resume_identity(
                    partial.get("fingerprint") if partial else None, fingerprint
                )
                training = root / partial["path"]
                request["resume_iteration"] = partial["checkpoint"]
                offset.update(
                    iteration=partial["checkpoint"], total=request["iterations"]
                )
                with log.open("a") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "m4ml_resume": {
                                    "offset": partial["checkpoint"],
                                    "total": request["iterations"],
                                    "previous_job": Path(partial["path"]).parts[1],
                                }
                            }
                        )
                        + "\n"
                    )
            else:
                training = output / "training"
            atomic_json(output / "input_fingerprint.json", fingerprint)
            atomic_json(
                output / "execution_settings.json", request.get("settings_snapshot", {})
            )

            def remember_partial(doc_path=training):
                found = provider("training").checkpoints(doc_path)
                usable = [i for i in found if i < request["iterations"]]
                if usable:
                    store.update(project_id, lambda doc: doc.update(training_partial={
                        "path": str(doc_path.relative_to(root)), "checkpoint": usable[-1],
                        "iterations": request["iterations"], "fingerprint": fingerprint, "time": now()}))

            try:
                result = engine.train(ctx, scene, training, request)
            except BaseException:
                remember_partial()
                raise
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
                doc.pop("training_partial", None)
                doc["training"] = {
                    "path": str(training.relative_to(root)),
                    "iterations": request["iterations"],
                    "revision": doc["revision"],
                    "gaussians": len(vertices),
                    "gpu": request["gpu"],
                    "ply_sha256": sha256(ply),
                    "resumed_from": result.get("resumed_from"),
                    "engine": provider("training").key,
                    "settings_snapshot": request.get("settings_snapshot"),
                }
                doc["stages"]["train"] = "completed"

            store.update(project_id, finish)

        elif stage == "mesh":
            progress("학습 결과를 렌더링하고 색상이 있는 3D 모델을 만들고 있습니다.")
            training = root / p["training"]["path"]
            (output / "mesh").mkdir(parents=True, exist_ok=True)
            report = engine.extract(
                ctx,
                root / p["scene"],
                training,
                p["training"]["iterations"],
                output / "mesh",
                request,
            )

            def finish(doc):
                doc["mesh"] = {
                    "path": str((output / "mesh").relative_to(root)),
                    **report,
                    "iterations": p["training"]["iterations"],
                    "engine": engine.key,
                    "settings_snapshot": request.get("settings_snapshot"),
                }
                doc["stages"]["mesh"] = "completed"

            store.update(project_id, finish)

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

        def failed(doc):
            if stage == "preview":
                doc["stages"]["sam"] = "completed" if doc["masks"] else "waiting_for_user"
                if request.get("session_id"):
                    from studio.live_prompt import matches

                    if matches(doc, request) and doc.get("live_prompt", {}).get("status") == "pending":
                        doc["live_prompt"].update(status="failed", error=message)
            else:
                doc["stages"][stage] = state

        store.update(project_id, failed)
        if stage == "colmap" and (output / "colmap/report.json").is_file():
            report = json.loads((output / "colmap/report.json").read_text())
            store.update(project_id, lambda doc: doc.update(colmap_report=report))
        raise
    finally:
        if lock:
            lock.close()
    if stage == "train" and store.job(job_id)["state"] == "completed":
        # Training was explicitly approved at the API gate. 3D model generation is
        # the next unattended stage and starts only after the GPU lock is released.
        from studio.dispatch import launch

        launch(
            store,
            project_id,
            "mesh",
            {
                "gpu": request["gpu"],
                "gpu_uuid": request.get("gpu_uuid", str(request["gpu"])),
                **request.get(
                    "mesh_request", {"mesh_res": request.get("mesh_res", 1024)}
                ),
            },
        )


if __name__ == "__main__":
    run_job(sys.argv[1])
