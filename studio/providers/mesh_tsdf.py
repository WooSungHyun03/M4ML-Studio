"""3D model (mesh) generation provider: original 2DGS ``render.py`` bounded TSDF fusion.

``render.py`` fuses rendered RGB + depth into an Open3D TSDF volume and writes
``fuse.ply`` / ``fuse_post.ply`` with per-vertex RGB. The color is produced here; the
export provider only validates and converts it, never invents or recolors it.
"""

from __future__ import annotations

from pathlib import Path
import shutil

from studio.doctor import ROOT
from studio.providers.base import MeshProvider


class ObjectAwareTSDFMeshProvider(MeshProvider):
    key = "object_aware_tsdf"
    display_name = "2DGS TSDF fusion (original render.py, Open3D)"

    def info(self):
        base = super().info()
        base.update(
            entrypoint=str(ROOT / "render.py"),
            output="fuse_post.ply (vertex RGB)",
            default_mesh_res=self.options.get("mesh_res", 1024),
            license="Gaussian-Splatting License — non-commercial research/evaluation only",
        )
        return base

    def extract(self, ctx, scene, model, iterations, output, request):
        mesh_res = int(request.get("mesh_res", self.options.get("mesh_res", 1024)))
        ctx.python([
            "render.py", "-s", str(scene), "-m", str(model),
            "--skip_train", "--skip_test", "--mesh_res", str(mesh_res),
            "--iteration", str(iterations),
        ])
        ply = Path(model) / "train" / f"ours_{iterations}" / "fuse_post.ply"
        if not ply.is_file():
            raise ValueError("3D 모델 파일이 생성되지 않았습니다. 로그를 확인하세요.")
        from studio.engines import provider

        report = provider("export").validate_and_preview(ply, Path(output))
        shutil.copyfile(ply, Path(output) / "fuse_post.ply")
        report["mesh_res"] = mesh_res
        return report
