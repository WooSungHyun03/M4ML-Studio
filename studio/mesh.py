from pathlib import Path
import numpy as np

from studio.doctor import atomic_json, sha256


def validate_mesh(path, output=None):
    import trimesh

    mesh = trimesh.load(str(path), force="mesh", process=False)
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(
            "점 구름은 삼각형 메시가 아닙니다. TSDF 추출 결과를 선택하세요."
        )
    if (
        len(mesh.vertices) == 0
        or len(mesh.faces) == 0
        or not np.isfinite(mesh.vertices).all()
    ):
        raise ValueError(
            "유효한 삼각형 메시가 없습니다. 학습 결과와 추출 설정을 확인하세요."
        )
    if (
        mesh.faces.shape[1] != 3
        or np.any(mesh.faces < 0)
        or np.any(mesh.faces >= len(mesh.vertices))
    ):
        raise ValueError("메시의 삼각형 인덱스가 유효하지 않습니다.")
    report = {
        "vertices": len(mesh.vertices),
        "triangles": len(mesh.faces),
        "bounds": mesh.bounds.tolist(),
        "sha256": sha256(path),
        "colors": bool(mesh.visual.defined),
    }
    if output:
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        mesh.export(output / "preview.glb")
        # Export load-back is part of success validation.
        preview = trimesh.load(output / "preview.glb", force="mesh", process=False)
        if (
            len(preview.faces) != len(mesh.faces)
            or not np.isfinite(preview.vertices).all()
        ):
            raise ValueError("미리보기 메시 변환을 검증하지 못했습니다.")
        atomic_json(output / "mesh_report.json", report)
    return report
