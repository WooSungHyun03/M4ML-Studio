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
        # Original render.py writes train/ours_* under -m. Isolate those writes on every extraction.
        work = Path(output).parent / "extraction-model"
        work.mkdir(parents=True, exist_ok=False)
        from studio.result_artifacts import safe_model_config
        (work/"cfg_args").write_text(safe_model_config(model,source=scene,target=work))
        (work / "point_cloud").symlink_to(
            (Path(model) / "point_cloud").resolve(), target_is_directory=True
        )
        argv = [
            "render.py",
            "-s",
            str(scene),
            "-m",
            str(work),
            "--skip_train",
            "--skip_test",
            "--mesh_res",
            str(mesh_res),
            "--iteration",
            str(iterations),
        ]
        supported = {f["native"] for f in self.task_settings_schema()} - {"mesh_res"}
        for key, value in request.get("parameters", {}).items():
            if key not in supported:
                continue
            if type(value) is bool:
                if value:
                    argv.append("--" + key)
            else:
                argv += ["--" + key, str(value)]
        ctx.python(argv)
        ply = work / "train" / f"ours_{iterations}" / "fuse_post.ply"
        if not ply.is_file():
            raise ValueError("3D 모델 파일이 생성되지 않았습니다. 로그를 확인하세요.")
        from studio.engines import provider

        report = provider("export").validate_and_preview(ply, Path(output))
        shutil.copyfile(ply, Path(output) / "fuse_post.ply")
        report["mesh_res"] = mesh_res
        return report
