"""Build source+offline-UI research bundle, excluding environments, data and weights."""

import argparse, hashlib, io, json, os, shutil, subprocess, tarfile, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))
from studio.config import VERSION  # noqa: E402


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--internal-research", action="store_true", help="내부 검증용 빌드. 공개 재배포 승인이 아닙니다.")
    args = parser.parse_args()
    if (ROOT / "runtime/colmap/bin/colmap").is_file() and not args.internal_research:
        raise SystemExit("내장 런타임의 공개 재배포 검토가 미완료입니다. 내부 검증은 --internal-research로 빌드하세요.")
    out = ROOT / "release"
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="m4ml-package-") as d:
        app = Path(d) / f"M4ML-Studio-{VERSION}"
        app.mkdir()
        ignored = shutil.ignore_patterns(
            ".git",
            "__pycache__",
            "*.pyc",
            "*.so",
            "build",
            "*.egg-info",
            "node_modules",
            "*.tsbuildinfo",
        )
        for rel in [
            "studio",
            "scripts",
            "arguments",
            "scene",
            "utils",
            "gaussian_renderer",
            "lpipsPyTorch",
            "licenses",
            "patches",
            "docs",
            "frontend/dist",
            "frontend/public",
            "frontend/src",
            "frontend/tests",
            "Logo",
        ]:
            shutil.copytree(ROOT / rel, app / rel, ignore=ignored)
        for name in [
            "train.py",
            "render.py",
            "environment.yml",
            "requirements-anchor.txt",
            "requirements-runtime-constraints.txt",
            "requirements-studio.txt",
            "requirements-dev.txt",
            "requirements-viewer.txt",
            "README.md",
            "LICENSE.md",
            "NOTICE",
            "SOURCES.json",
            "frontend/package.json",
            "frontend/package-lock.json",
            "frontend/tsconfig.json",
            "frontend/vite.config.ts",
            "frontend/index.html",
            "AGENTS.md",
            "CODEX_PROMPT.md",
            "M4ML_STUDIO_RESUME_PROMPT.md",
        ]:
            shutil.copyfile(ROOT / name, app / name)
        # Relocatable GPU camera-reconstruction engine (built by scripts/build_colmap.sh).
        # Shipped as-is (shared libraries included) so users need no system COLMAP.
        engine = None
        if (ROOT / "runtime/colmap/bin/colmap").is_file():
            inventory = json.loads((ROOT / "licenses/colmap-runtime/inventory.json").read_text())
            if inventory["unresolved_notices"]:
                raise SystemExit("내장 런타임 라이선스 고지가 누락되어 있습니다.")
            for library in inventory["libraries"]:
                if digest(ROOT / "runtime/colmap/lib" / library["library"]) != library["sha256"]:
                    raise SystemExit("런타임 변경 후 라이선스 인벤토리를 다시 생성하세요.")
            engine = json.loads((ROOT / "runtime/colmap/BUILD_INFO.json").read_text())
            shutil.copytree(ROOT / "runtime/colmap", app / "runtime/colmap", symlinks=True)
        # Optional external Gaussian viewer (scripts/build_sibr.sh): SIBR's own libraries only,
        # verified against BUILD_INFO.json; Ubuntu system libraries are not bundled.
        if (ROOT / "runtime/sibr/bin/SIBR_remoteGaussian_app").is_file():
            sibr = json.loads((ROOT / "runtime/sibr/BUILD_INFO.json").read_text())
            for name, sha in sibr["bundled"].items():
                if digest(ROOT / "runtime/sibr/bin" / name) != sha:
                    raise SystemExit("runtime/sibr 파일이 BUILD_INFO.json과 다릅니다. ./scripts/build_sibr.sh를 다시 실행하세요.")
            shutil.copytree(ROOT / "runtime/sibr", app / "runtime/sibr", symlinks=True)
        for rel in ["submodules/diff-surfel-rasterization", "submodules/simple-knn"]:
            shutil.copytree(ROOT / rel, app / rel, ignore=ignored)
        # Archive actual official source, not the submodule's machine-local .git link.
        sam = app / "vendor/sam3"
        sam.mkdir(parents=True)
        raw = subprocess.check_output(
            ["git", "archive", "HEAD"], cwd=ROOT / "vendor/sam3"
        )
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            for member in archive:
                if not member.isfile():
                    continue
                if member.name.startswith("sam3/") or member.name in {
                    "pyproject.toml",
                    "README.md",
                    "LICENSE",
                    "LICENSE.txt",
                    "assets/bpe_simple_vocab_16e6.txt.gz",
                }:
                    target = sam / member.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
        (sam / ".source-revision").write_text(
            json.loads((ROOT / "SOURCES.json").read_text())["sam31"]["revision"]
        )
        files = {
            p.relative_to(app).as_posix(): digest(p)
            for p in app.rglob("*")
            if p.is_file()
        }
        assert not any(
            n.endswith(
                (
                    ".pt",
                    ".pth",
                    ".ckpt",
                    ".safetensors",
                    ".db",
                    ".sqlite",
                    ".log",
                    ".ply",
                    ".glb",
                )
            )
            for n in files
        )
        manifest = {
            "product": "M4ML Studio",
            "version": VERSION,
            "channel": "internal-research" if args.internal_research else "research-preview",
            "public_redistribution_approved": False,
            "redistribution_blockers": ["SuiteSparse GPL/LGPL corresponding-source and relinking compliance", "License compatibility and noncommercial research restrictions; no legal review"],
            "files_sha256": files,
            "weights_included": False,
            "camera_engine": (
                {k: engine.get(k) for k in ("engine", "tag", "commit", "profile", "cuda_architectures", "cuda_toolkit", "binary_sha256")}
                if engine
                else None
            ),
        }
        (app / "release-manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False)
        )
        target = out / f"M4ML-Studio-{VERSION}-linux-x86_64.tar.gz"
        with tarfile.open(target, "w:gz") as archive:
            archive.add(app, arcname=app.name)
        (out / (target.name + ".sha256")).write_text(
            f"{digest(target)}  {target.name}\n"
        )
        print(
            target, len(files), "files", target.stat().st_size, "bytes", digest(target)
        )


if __name__ == "__main__":
    main()
