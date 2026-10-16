"""Bounded process groups, literal argv, durable output and cooperative cancellation."""

import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import sys


class Cancelled(RuntimeError):
    pass


def signal_owned_worker(pid, job_id):
    """Never signal a recycled PID; a pidfd pins the checked process on Linux."""
    descriptor = None
    try:
        if hasattr(os, "pidfd_open"):
            descriptor = os.pidfd_open(pid)
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        if b"studio.worker" not in argv or job_id.encode() not in argv:
            return False
        if descriptor is not None and hasattr(signal, "pidfd_send_signal"):
            signal.pidfd_send_signal(descriptor, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except (FileNotFoundError, ProcessLookupError):
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)


def failure_message(log_path, error):
    path = Path(log_path)
    if path.is_file():
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 16000))
            tail = stream.read().decode("utf-8", errors="replace").lower()
        if "out of memory" in tail or "cuda_error_out_of_memory" in tail:
            return "GPU 메모리가 부족합니다. 다른 GPU 작업을 종료하거나 학습 사진 해상도를 낮춘 뒤 다시 시도하세요. 원본 로그를 보존했습니다."
    return str(error)


def run(argv, log_path, *, cwd=None, env=None, cancel=None, timeout=7200, on_line=None):
    argv = [os.fspath(arg) for arg in argv]
    cancel = cancel or threading.Event()
    if cancel.is_set():
        raise Cancelled("작업이 취소되었습니다.")
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with log_path.open("a", buffering=1) as log:
        import json

        log.write(
            json.dumps(
                {"argv": argv, "cwd": str(cwd), "started": time.time()},
                ensure_ascii=False,
            )
            + "\n"
        )
        protected = [
            sys.executable,
            str(Path(__file__).with_name("child.py")),
            str(os.getpid()),
            *argv,
        ]
        with subprocess.Popen(
            protected,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
            errors="replace",
            bufsize=1,
        ) as child:

            def consume():
                for line in child.stdout:
                    log.write(line)
                    if on_line:
                        on_line(line)

            reader = threading.Thread(target=consume, daemon=True)
            reader.start()
            interrupted = False
            try:
                while child.poll() is None:
                    if cancel.wait(0.1) or time.monotonic() - started > timeout:
                        interrupted = True
                        os.killpg(child.pid, signal.SIGTERM)
                        try:
                            child.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait()
                        break
                reader.join(timeout=10)
            finally:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                reader.join(timeout=2)
                child.stdout.close()
            log.write(
                json.dumps(
                    {
                        "exit_code": child.returncode,
                        "seconds": time.monotonic() - started,
                    }
                )
                + "\n"
            )
            if interrupted:
                if cancel.is_set():
                    raise Cancelled(
                        "작업이 취소되었습니다. 중간 파일과 로그를 보존했습니다."
                    )
                raise TimeoutError("작업 제한 시간을 초과했습니다. 로그를 확인하세요.")
            if child.returncode:
                raise RuntimeError(
                    f"실행에 실패했습니다 (종료 코드 {child.returncode}). 로그: {log_path}"
                )
