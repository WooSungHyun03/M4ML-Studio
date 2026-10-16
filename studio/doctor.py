"""Read-only, reproducible host inventory; never treats inventory as GPU E2E proof."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def command(argv, cwd=ROOT, timeout=45):
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return {"argv": argv, "exit_code": result.returncode, "output": result.stdout}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": argv, "exit_code": None, "error": str(exc)}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".report-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def archive_provenance(root):
    try:
        sources = json.loads((root / "SOURCES.json").read_text())
        for name, expected in sources["object_aware"]["files_sha256"].items():
            if sha256(root / name) != expected:
                raise ValueError("원본 소스가 변경되었습니다: " + name)
        if (root / "vendor/sam3/.source-revision").read_text().strip() != sources[
            "sam31"
        ]["revision"]:
            raise ValueError("SAM 소스 revision이 다릅니다.")
        return {
            "argv": ["archive-source-provenance"],
            "exit_code": 0,
            "output": "배포 소스의 원본 연구 코드 hash와 공식 SAM pin 확인",
        }
    except (OSError, ValueError, KeyError) as e:
        return {"argv": ["archive-source-provenance"], "exit_code": 1, "error": str(e)}


def inventory(checkpoint_dir, hash_weights=True):
    checkpoints = []
    if checkpoint_dir.is_dir():
        for path in sorted(checkpoint_dir.rglob("*")):
            if path.is_file() and ".cache" not in path.parts:
                entry = {
                    "path": (
                        str(path.relative_to(ROOT))
                        if path.is_relative_to(ROOT)
                        else str(path)
                    ),
                    "bytes": path.stat().st_size,
                    "mtime_ns": path.stat().st_mtime_ns,
                }
                if hash_weights or path.suffix not in {".pt", ".pth", ".safetensors"}:
                    entry["sha256"] = sha256(path)
                checkpoints.append(entry)
    probes = {
        "source": ["git", "rev-parse", "HEAD"],
        "working_tree": ["git", "status", "--short", "--branch"],
        "remotes": ["git", "remote", "-v"],
        "submodules": ["git", "submodule", "status", "--recursive"],
        "gpu": [
            "nvidia-smi",
            "--query-gpu=index,name,uuid,driver_version,memory.total,memory.free,compute_cap",
            "--format=csv",
        ],
        "driver": ["nvidia-smi"],
        "nvcc_path": ["nvcc", "--version"],
        "cuda_anchor": [
            str(Path(os.environ.get("STUDIO_RUNTIME", sys.prefix)) / "bin/nvcc"),
            "--version",
        ],
        "colmap": [_colmap_path(), "help"],
        "ram": ["free", "-b"],
        "torch": [
            sys.executable,
            "-c",
            "import sys,torch,torchvision,numpy; print(sys.version,'torch',torch.__version__,'torchvision',torchvision.__version__,'cuda',torch.version.cuda,'numpy',numpy.__version__); assert sys.version_info[:2]==(3,10); assert torch.__version__.split('+')[0]=='2.5.1'; assert torchvision.__version__.split('+')[0]=='0.20.1'; assert torch.version.cuda=='11.8'; assert numpy.__version__=='1.24.4'; print('available',torch.cuda.is_available()); print('device',torch.cuda.get_device_name(0)); print('calculation', (torch.ones(4,device='cuda') * 2).tolist())",
        ],
        "native": [
            sys.executable,
            "-c",
            "import torch; import diff_surfel_rasterization._C; import simple_knn._C; import gaussian_renderer; print('native and original renderer imports PASS')",
        ],
    }
    results = {
        name: command(argv)
        for name, argv in probes.items()
        if (ROOT / ".git").exists()
        or name not in {"source", "working_tree", "remotes", "submodules"}
    }
    if not (ROOT / ".git").exists():
        results["archive_source"] = archive_provenance(ROOT)
    results["nvcc_path"]["required"] = False
    colmap_banner = results["colmap"].get("output", "") or ""
    results["colmap_gpu"] = {
        "argv": ["colmap-cuda-build-check"],
        "exit_code": 0 if "with CUDA" in colmap_banner else 1,
        "required": False,
        "output": (
            "카메라 정합 엔진이 GPU(CUDA) 빌드입니다."
            if "with CUDA" in colmap_banner
            else "카메라 정합 엔진이 CPU 전용입니다. ./scripts/build_colmap.sh 로 GPU 엔진을 빌드하세요."
        ),
    }
    from studio.config import checkpoint_path

    selected = checkpoint_path()
    results["checkpoint"] = {
        "argv": ["local-checkpoint-metadata"],
        "exit_code": (
            0 if selected.is_file() and selected.stat().st_size > 1024**3 else 1
        ),
        "output": (
            "체크포인트 파일 확인 · 실제 구조/추론 검증은 별도"
            if selected.is_file()
            else "SAM3.1 체크포인트를 준비하고 환경 설정에서 경로를 지정하세요."
        ),
    }
    return {
        "schema_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(ROOT),
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "os_release": platform.freedesktop_os_release(),
        "disk": dict(zip(("total", "used", "free"), shutil.disk_usage(ROOT))),
        "checkpoints": checkpoints,
        "probes": results,
        "acceptance": {
            "SAM31_POINT": "NOT RUN",
            "SAM31_PROPAGATION": "NOT RUN",
            "OBJECT_AWARE_TRAIN": "NOT RUN",
            "MESH": "NOT RUN",
        },
    }


def _colmap_path():
    try:
        from studio.engines import colmap_binary

        return str(colmap_binary()[0])
    except Exception:
        return "colmap"


def main():
    parser = argparse.ArgumentParser(
        description="실제 장비와 설치 상태를 확인합니다. 추론 검증과는 별개입니다."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        / "m4ml-studio/doctor.json",
    )
    from studio.config import checkpoint_path

    parser.add_argument("--checkpoint-dir", type=Path, default=checkpoint_path().parent)
    parser.add_argument("--skip-weight-hash", action="store_true")
    args = parser.parse_args()
    report = inventory(args.checkpoint_dir.resolve(), not args.skip_weight_hash)
    atomic_json(args.output, report)
    print(f"진단 기록: {args.output.resolve()}")
    failures = []
    for name, result in report["probes"].items():
        passed = result["exit_code"] == 0
        print(f"{name}: {'확인' if passed else '실패'}")
        if not passed and result.get("required", True):
            failures.append(name)
            print(result.get("output", result.get("error")))
    print("SAM 3.1 실제 클릭·전파 및 학습·메시 검증: 별도 실행 필요")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
