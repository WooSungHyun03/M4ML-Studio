"""User desktop launcher: private instance lock, no GPU imports, bounded shutdown."""

import fcntl, json, os, signal, subprocess, sys, time, urllib.request, webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "m4ml-studio"
)
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "m4ml-studio"


def main():
    CACHE.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = {}
    try:
        config = json.loads((CONFIG / "install.json").read_text())
    except (FileNotFoundError, ValueError):
        pass
    runtime = (
        os.environ.get("STUDIO_RUNTIME")
        or config.get("runtime")
        or str(ROOT / ".runtime")
    )
    port = int(os.environ.get("STUDIO_PORT", 8765))
    url = f"http://127.0.0.1:{port}"
    lock = (CACHE / "instance.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=5) as response:
                assert json.load(response)["app"] == "M4ML Studio"
            if "--no-browser" not in sys.argv:
                webbrowser.open(url)
            return 0
        except Exception:
            raise SystemExit(
                "다른 M4ML Studio가 시작 중입니다. 잠시 후 다시 실행하세요."
            )
    # A manually started trusted local backend can be reused without spawning a duplicate.
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=2) as response:
            existing = json.load(response)
        if existing.get("app") == "M4ML Studio":
            if "--no-browser" not in sys.argv:
                webbrowser.open(url)
            return 0
        raise SystemExit(
            "포트를 다른 프로그램이 사용 중입니다. STUDIO_PORT를 바꾸세요."
        )
    except (OSError, ValueError):
        pass
    env = os.environ.copy()
    env["STUDIO_RUNTIME"] = runtime
    with (CACHE / "launcher.log").open("a") as log:
        child = subprocess.Popen(
            [str(ROOT / "scripts/start.sh")],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        def stop(*_):
            if child.poll() is None:
                child.terminate()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        ready = False
        for _ in range(150):
            if child.poll() is not None:
                break
            try:
                with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                    ready = json.load(response).get("app") == "M4ML Studio"
                if ready:
                    break
            except Exception:
                time.sleep(0.2)
        if not ready:
            stop()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            print(
                f'M4ML Studio 시작 실패. 포트 또는 런타임을 확인하세요. 로그: {CACHE / "launcher.log"}',
                file=sys.stderr,
            )
            return 1
        if "--no-browser" not in sys.argv:
            webbrowser.open(url)
        try:
            code = child.wait()
            return 0 if code in (0, -signal.SIGTERM, -signal.SIGINT) else code
        finally:
            stop()


if __name__ == "__main__":
    sys.exit(main())
