"""Per-user install/update/unregister; project data and runtime are preserved."""

import argparse, errno, hashlib, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def tree_contents(root):
    contents = {}
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(base) / name
            key = path.relative_to(root).as_posix()
            if path.is_symlink():
                contents[key] = ("link", os.readlink(path))
            elif path.is_dir():
                contents[key] = ("directory",)
            else:
                with path.open("rb") as stream:
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                contents[key] = ("file", digest.hexdigest())
    return contents


def retire_app(app, target):
    """OverlayFS lower directories can reject rename even within one mount.

    Publish a fully verified copy before removing the owned application tree.
    Project/runtime paths are never passed here. Preserve symlinks as links.
    """
    try:
        app.rename(target)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    original = tree_contents(app)
    with tempfile.TemporaryDirectory(prefix=".retire-", dir=target.parent) as temp:
        staged = Path(temp) / "app"
        shutil.copytree(app, staged, symlinks=True)
        if tree_contents(staged) != original or tree_contents(app) != original:
            raise OSError("이전 설치 사본 검증에 실패했습니다. 원본을 보존했습니다.")
        staged.rename(target)
    # A complete backup exists before any original file is removed.
    for base, dirs, files in os.walk(app, followlinks=False):
        Path(base).chmod(Path(base).stat().st_mode | 0o700)
    shutil.rmtree(app)


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
            if app.is_symlink():
                raise SystemExit("설치 폴더의 심볼릭 링크는 자동 제거하지 않습니다.")
            app.chmod(mode | 0o200)
            try:
                retire_app(app, target)
            except BaseException:
                if app.exists():
                    app.chmod(mode)
                raise
            target.chmod(mode)
        if launcher.exists():
            launcher.unlink()
        if registry.exists():
            registry.unlink()
        print(
            "M4ML Studio 실행 메뉴를 제거했습니다. 프로젝트·런타임·이전 설치본은 보존했습니다."
        )
        return
    manifest = json.loads((ROOT / "release-manifest.json").read_text())
    for name, expected in manifest["files_sha256"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise SystemExit("설치 파일 경로가 올바르지 않습니다: " + name)
        p = ROOT / name
        if not p.resolve().is_relative_to(ROOT.resolve()) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise SystemExit("설치 파일 검증 실패: " + name)
    version = manifest["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise SystemExit("설치 버전이 올바르지 않습니다.")
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
        # An extraction folder can also contain a user's weights, .env or old
        # files. Install only verified manifest entries, atomically; retain ROOT.
        with tempfile.TemporaryDirectory(prefix=".install-", dir=app.parent) as temp:
            staged = Path(temp) / version
            staged.mkdir()
            for name in [*manifest["files_sha256"], "release-manifest.json"]:
                target = staged / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
            staged.rename(app)
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
        "[Desktop Entry]\nType=Application\nVersion=1.0\nName=M4ML Studio\nComment=사진으로 3D 모델 만들기\nExec=python3 "
        + quoted(app / "scripts/launch.py")
        + "\nIcon="
        + str(app / "frontend/public/m4ml-icon.png")
        + "\nTerminal=false\nCategories=Graphics;3DGraphics;\nStartupNotify=true\nStartupWMClass=m4ml-studio\n"
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
