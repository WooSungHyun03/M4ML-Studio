"""Build source+offline-UI research bundle, excluding environments, data and weights."""

import argparse, gzip, hashlib, io, json, os, shutil, subprocess, tarfile, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))
from studio.config import VERSION  # noqa: E402


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_bundle(app, target, epoch):
    """Reproducible archive, published atomically without replacing an older build."""
    def metadata(member):
        member.uid = member.gid = 0
        member.uname = member.gname = ""
        member.mtime = epoch
        member.mode = 0o755 if member.isdir() or member.mode & 0o111 else 0o644
        return member

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".partial") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as archive:
                archive.add(app, arcname=app.name, filter=metadata)
        raw.flush()
        os.fsync(raw.fileno())
        os.fchmod(raw.fileno(), 0o644)
        os.link(raw.name, target)  # exclusive publication; never truncate an existing build


def verify_corresponding_source(src: Path) -> Path:
    """Every file listed in SHA256SUMS matches, and the copyleft packages match the inventory."""
    sums = (src / "SHA256SUMS").read_text().splitlines()
    listed = {}
    for line in sums:
        sha, name = line.split(None, 1)
        name = name.strip().lstrip("*").removeprefix("./")
        if digest(src / name) != sha:
            raise SystemExit(f"대응 소스 해시 불일치: {name}")
        listed[name] = sha
    inventory = json.loads((ROOT / "licenses/colmap-runtime/inventory.json").read_text())
    needed = set()
    for library in inventory["libraries"]:
        source = library["build_packages"][0].split("source=")[-1]
        package, _, version = source.partition(" ")
        if package in ("suitesparse", "gcc-14", "ceres-solver"):
            needed.add(f"ubuntu-source/{package}_{version.split(':')[-1]}.dsc")
    missing = sorted(n for n in needed if n not in listed)
    if missing:
        raise SystemExit("대응 소스에 필요한 패키지가 없습니다: " + ", ".join(missing))
    if f"upstream/colmap-{inventory['colmap_commit']}.tar.gz" not in listed:
        raise SystemExit("대응 소스에 COLMAP 원본이 없습니다.")
    return src


def write_source_bundle(src: Path, target: Path, epoch: int):
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as raw:
        with tarfile.open(fileobj=raw, mode="w") as archive:
            for path in sorted(p for p in src.rglob("*") if p.is_file()):
                info = archive.gettarinfo(str(path), arcname=f"{target.name.removesuffix('.tar')}/{path.relative_to(src).as_posix()}")
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = epoch
                info.mode = 0o644
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
    os.link(raw.name, target)
    os.unlink(raw.name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--internal-research", action="store_true", help="내부 검증용 빌드. 공개 재배포 승인이 아닙니다.")
    parser.add_argument("--output-dir", type=Path, help="기존 압축본을 보존할 별도 후보 출력 폴더")
    parser.add_argument("--corresponding-source", type=Path,
                        help="scripts/collect_corresponding_source.sh 결과 폴더 (내장 런타임의 GPL/LGPL 대응 소스)")
    args = parser.parse_args()
    corresponding = None
    if (ROOT / "runtime/colmap/bin/colmap").is_file() and not args.internal_research:
        # A release that redistributes the copyleft runtime must ship its corresponding source.
        if not args.corresponding_source:
            raise SystemExit("내장 런타임을 배포하려면 --corresponding-source로 대응 소스 폴더를 지정하세요.")
        corresponding = verify_corresponding_source(args.corresponding_source.resolve())
    out = (args.output_dir or ROOT / "release").resolve()
    out.mkdir(parents=True, exist_ok=True)
    bundle_target = out / f"M4ML-Studio-{VERSION}-linux-x86_64.tar.gz"
    if bundle_target.exists() or bundle_target.with_name(bundle_target.name + ".sha256").exists():
        raise SystemExit("기존 배포 파일을 보존했습니다. --output-dir로 새 후보 폴더를 지정하세요.")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH") or subprocess.check_output(
        ["git", "show", "-s", "--format=%ct", "HEAD"], cwd=ROOT, text=True).strip())
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
            "CHANGELOG.md",
            "RELEASE_NOTES.md",
            "THIRD_PARTY_NOTICES.md",
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
        corresponding_record = None
        if corresponding:
            source_target = out / f"M4ML-Studio-{VERSION}-corresponding-source.tar"
            if source_target.exists():
                raise SystemExit("기존 대응 소스 파일을 보존했습니다. --output-dir로 새 폴더를 지정하세요.")
            write_source_bundle(corresponding, source_target, epoch)
            (out / (source_target.name + ".sha256")).write_text(f"{digest(source_target)}  {source_target.name}\n")
            corresponding_record = {"file": source_target.name, "sha256": digest(source_target),
                                    "covers": "runtime/colmap (SuiteSparse GPL/LGPL, GCC 14 runtime, Ceres, COLMAP, OpenImageIO)"}
            shutil.copyfile(corresponding / "README.txt", app / "licenses/CORRESPONDING-SOURCE.txt")
            with (app / "licenses/CORRESPONDING-SOURCE.txt").open("a") as note:
                note.write(f"\nSource archive: {source_target.name}\nSHA256: {corresponding_record['sha256']}\n"
                           "Published next to this package on the same release page.\n")
        from studio.release_inventory import inventory
        (app / "licenses/sbom.json").write_text(
            json.dumps(inventory(app), indent=2, ensure_ascii=False) + "\n"
        )
        files = {
            p.relative_to(app).as_posix(): digest(p)
            for p in sorted(app.rglob("*"))
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
            "channel": "internal-research" if args.internal_research else "noncommercial-release",
            "use": "non-commercial research and evaluation only (LICENSE.md; SIBR/Gaussian-Splatting/SAM terms)",
            "commercial_use_permitted": False,
            "corresponding_source": corresponding_record,
            "files_sha256": files,
            "weights_included": False,
            "source_commit": commit,
            "camera_engine": (
                {k: engine.get(k) for k in ("engine", "tag", "commit", "profile", "cuda_architectures", "cuda_toolkit", "binary_sha256")}
                if engine
                else None
            ),
        }
        (app / "release-manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False)
        )
        write_bundle(app, bundle_target, epoch)
        (out / (bundle_target.name + ".sha256")).write_text(
            f"{digest(bundle_target)}  {bundle_target.name}\n"
        )
        print(
            bundle_target, len(files), "files", bundle_target.stat().st_size, "bytes", digest(bundle_target)
        )


if __name__ == "__main__":
    main()
