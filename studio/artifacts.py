"""Content identity for checkpoint resumes, independent of provider implementation."""
from pathlib import Path

from studio.doctor import sha256


def dataset_identity(scene: Path, names) -> dict:
    scene = scene.resolve()
    files = [scene / "images" / name for name in sorted(names)]
    sparse = scene / "sparse/0"
    for stem in ("cameras", "images", "points3D"):
        files.append(sparse / (stem + (".bin" if (sparse / (stem + ".bin")).is_file() else ".txt")))
    hashes = {}
    for path in files:
        if not path.resolve().is_relative_to(scene) or not path.is_file():
            raise ValueError("학습 데이터 경로가 잘못되었거나 파일이 없습니다. 사진과 카메라 정합 결과를 확인하세요.")
        hashes[path.relative_to(scene).as_posix()] = sha256(path)
    return {"schema_version": 1, "files_sha256": hashes}


def require_resume_identity(previous, current):
    if not previous or previous != current:
        raise ValueError("사진·카메라·마스크·설정이 바뀌었거나 이전 저장 지점에 데이터 검증 기록이 없습니다. 기존 파일은 보존했습니다. 새로 학습하세요.")
