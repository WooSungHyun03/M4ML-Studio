"""User launcher.

Default: the standalone desktop window (PySide6 + QtWebEngine, ``studio.desktop``), which starts
and stops its own loopback backend on a free port. ``--browser`` keeps the developer mode
(backend on STUDIO_PORT, opened in the system browser); ``--no-browser`` starts only the backend.
No GPU imports here; bounded shutdown."""

import fcntl, json, os, signal, subprocess, sys, time, urllib.request, webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "m4ml-studio"
)
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "m4ml-studio"


def runtime_python():
    config = {}
    try:
        config = json.loads((CONFIG / "install.json").read_text())
    except (FileNotFoundError, ValueError):
        pass
    runtime = os.environ.get("STUDIO_RUNTIME") or config.get("runtime") or str(ROOT / ".runtime")
    return runtime, Path(runtime) / "bin/python"


def desktop():
    """Replace this process with the desktop shell; False if its Qt runtime is not installed."""
    runtime, python = runtime_python()
    probe = subprocess.run(
        [str(python), "-c", "import PySide6.QtWebEngineWidgets"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe.returncode != 0:
        return False
    env = os.environ.copy()
    env["STUDIO_RUNTIME"] = runtime
    os.chdir(ROOT)
    os.execve(str(python), [str(python), "-m", "studio.desktop"], env)


def main():
    CACHE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if "--browser" not in sys.argv and "--no-browser" not in sys.argv:
        if desktop() is False:
            print(
                "데스크톱 창 구성요소(PySide6)를 찾지 못해 브라우저 모드로 엽니다. ./scripts/setup.sh를 다시 실행하면 데스크톱 창을 사용할 수 있습니다.",
                file=sys.stderr,
            )
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
