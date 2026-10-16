"""Actual CPU workers: thread retirement, cancellation and server-death cleanup.

Never substitutes inference/training. All files are retained under --output.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio.dispatch import launch
from studio.doctor import atomic_json
from studio.store import Store


def wait_job(store, job_id, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = store.job(job_id)
        if job["state"] != "running":
            return job
        time.sleep(0.1)
    raise TimeoutError(f"worker did not terminate: {job_id}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--images", type=Path)
    parser.add_argument("--controller", action="store_true")
    args = parser.parse_args()
    if args.controller:
        store = Store(args.output)
        project = store.list()[0]
        job_id = launch(store, project["id"], "colmap", {})
        print(json.dumps({"job_id": job_id}), flush=True)
        time.sleep(120)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    results = {}
    store = Store(args.output / "retired-thread")
    project = store.create("요청 스레드 종료 회귀")
    captured = []
    thread = threading.Thread(
        target=lambda: captured.append(launch(store, project["id"], "colmap", {}))
    )
    thread.start()
    thread.join()
    failed = wait_job(store, captured[0])
    assert failed["state"] == "failed", failed
    assert "취소" not in failed["message"], failed
    results["retired_thread_still_runs_worker_and_reports_real_colmap_failure"] = failed
    store = Store(args.output / "cancel-startup")
    project = store.create("시작 직후 취소")
    job_id = launch(store, project["id"], "colmap", {})
    store.job_update(job_id, cancel_requested=1)
    try:
        os.kill(store.job(job_id)["pid"], signal.SIGTERM)
    except ProcessLookupError:
        pass
    cancelled = wait_job(store, job_id)
    assert cancelled["state"] == "cancelled", cancelled
    results["startup_cancel_never_completed"] = cancelled
    if args.images:
        store = Store(args.output / "server-death")
        project = store.create("서버 강제 종료 복구")
        target = store.path(project["id"]) / "input/original"
        shutil.copytree(args.images, target)
        env = os.environ.copy()
        env.pop("STUDIO_OWNER_PID", None)
        env.pop("STUDIO_OWNER_START", None)
        with subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--controller",
                "--output",
                str(store.root),
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as controller:
            info = json.loads(controller.stdout.readline())
            time.sleep(2)
            assert store.job(info["job_id"])["state"] == "running"
            controller.kill()
            controller.wait()
            result = wait_job(store, info["job_id"])
            assert result["state"] == "cancelled", result
            results["server_death_stops_real_colmap_child"] = result
            controller.stdout.close()
            controller.stderr.close()
    atomic_json(args.output / "results.json", results)
    print("PASS", list(results), flush=True)


if __name__ == "__main__":
    main()
