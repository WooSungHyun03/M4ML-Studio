import os
import subprocess
import sys
from studio.doctor import ROOT
from studio.store import invalidate


def launch(store, project_id, stage, request):
    from studio.task_settings import execution

    if "settings_snapshot" not in request:
        request = execution(store.get(project_id), stage, request)
    job_id = store.new_job(project_id, stage, request)
    target_stage = "sam" if stage == "preview" else stage

    def begin(p):
        if stage != "preview":
            invalidate(p, target_stage)
        p["stages"][target_stage] = "running"

    store.update(project_id, begin)
    log = store.path(project_id) / "logs" / (job_id + "-worker.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["STUDIO_DATA"] = str(store.root)
    # API requests may run in short-lived thread-pool threads. Linux
    # PDEATHSIG tracks the creating *thread*, so it is wrong for API workers.
    # Persist the owning server process identity; worker monitors that process.
    if "STUDIO_OWNER_PID" not in env:
        env["STUDIO_OWNER_PID"] = str(os.getpid())
        from pathlib import Path

        env["STUDIO_OWNER_START"] = (
            Path(f"/proc/{os.getpid()}/stat").read_text().split()[21]
        )
    try:
        with log.open("a") as stream:
            process = subprocess.Popen(
                [sys.executable, "-m", "studio.worker", job_id],
                cwd=ROOT,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        store.job_update(job_id, pid=process.pid)
        # Reap without keeping an event loop or HTTP request blocked.
        import threading

        def reap():
            code = process.wait()
            record = store.job(job_id)
            if record["state"] == "running":
                state = "cancelled" if record["cancel_requested"] else "failed"
                store.job_update(
                    job_id,
                    state=state,
                    exit_code=code,
                    message=(
                        "작업이 취소되었습니다."
                        if state == "cancelled"
                        else "작업 프로세스가 예기치 않게 종료되었습니다. 로그를 확인하세요."
                    ),
                )
                store.update(
                    project_id, lambda p: p["stages"].update({target_stage: state})
                )

        threading.Thread(target=reap, daemon=True).start()
    except BaseException:
        store.job_update(
            job_id, state="failed", message="작업 프로세스를 시작하지 못했습니다."
        )
        store.update(project_id, lambda p: p["stages"].update({target_stage: "failed"}))
        raise
    return job_id
