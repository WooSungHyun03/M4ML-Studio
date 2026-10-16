"""Per-user install/update/unregister; project data and runtime are preserved."""

import argparse, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(data)
    temp.replace(path)


def quoted(value):
    return (
        '"'
        + str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
        + '"'
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-setup", action="store_true", help="등록만 수행; 별도 런타임이 필요함"
    )
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument(
        "--viewer-only",
        action="store_true",
        help="GPU 없이 결과 보기·데이터 관리만 설치",
    )
    args = parser.parse_args()
    import fcntl

    cache = (
        Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "m4ml-studio"
    )
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    install_lock = (cache / "instance.lock").open("a")
    try:
        fcntl.flock(install_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(
            "M4ML Studio를 종료한 뒤 설치·업데이트·제거를 다시 실행하세요."
        )
    data = (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        / "m4ml-studio"
    )
    config = (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "m4ml-studio"
    )
    apps = data.parent / "applications"
    config.mkdir(parents=True, exist_ok=True)
    launcher = apps / "m4ml-studio.desktop"
    registry = config / "install.json"
    if args.uninstall:
        # Remove only generated integration files. Application bits are archived, projects/runtime untouched.
        current = json.loads(registry.read_text()) if registry.exists() else {}
        if launcher.exists():
            launcher.unlink()
        app = Path(current.get("app", ""))
        if (
            app.name == str(current.get("version", "0.2.0"))
            and app.name not in {"", ".", ".."}
            and app.parent == data / "apps"
            and (app / "release-manifest.json").is_file()
        ):
            archive = data / "retired-apps"
            archive.mkdir(exist_ok=True)
            import uuid

            target = archive / (app.name + "-" + uuid.uuid4().hex)
            mode = app.stat().st_mode
            if app.stat().st_uid != os.getuid():
                raise SystemExit("현재 사용자 소유의 설치만 제거할 수 있습니다.")
            app.chmod(mode | 0o200)
            try:
                app.rename(target)
            except BaseException:
                app.chmod(mode)
                raise
            target.chmod(mode)
        if registry.exists():
            registry.unlink()
        print(
            "M4ML Studio 실행 메뉴를 제거했습니다. 프로젝트·런타임·이전 설치본은 보존했습니다."
        )
        return
    manifest = json.loads((ROOT / "release-manifest.json").read_text())
    for name, expected in manifest["files_sha256"].items():
        p = ROOT / name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise SystemExit("설치 파일 검증 실패: " + name)
    version = manifest["version"]
    app = data / "apps" / version
    runtime = Path(os.environ.get("STUDIO_RUNTIME", data / "runtime"))
    if app.exists():
        if (app / "release-manifest.json").read_bytes() != (
            ROOT / "release-manifest.json"
        ).read_bytes():
            raise SystemExit(
                "다른 내용의 같은 버전 설치가 있습니다. 기존 설치를 보존했습니다."
            )
    else:
        app.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT, app)
    if not args.no_setup:
        env = os.environ.copy()
        env["STUDIO_RUNTIME"] = str(runtime)
        if args.viewer_only:
            env["STUDIO_VIEWER_ONLY"] = "1"
        subprocess.run([str(app / "scripts/setup.sh")], cwd=app, env=env, check=True)
    atomic(
        registry,
        json.dumps(
            {"version": version, "app": str(app), "runtime": str(runtime)}, indent=2
        ),
    )
    desktop = (
        "[Desktop Entry]\nType=Application\nVersion=1.0\nName=M4ML Studio\nComment=멀티뷰 사진으로 객체 컬러 3D 모델 만들기\nExec=python3 "
        + quoted(app / "scripts/launch.py")
        + "\nIcon="
        + str(app / "frontend/public/m4ml-icon.png")
        + "\nTerminal=false\nCategories=Graphics;3DGraphics;\nStartupNotify=true\n"
    )
    atomic(launcher, desktop)
    launcher.chmod(0o755)
    print("M4ML Studio 설치·실행 아이콘 등록 완료:", launcher)
    if args.no_setup:
        print(
            "런타임 설치는 생략했습니다. 이 결과만으로 GPU 설치 성공을 뜻하지 않습니다."
        )


if __name__ == "__main__":
    main()
