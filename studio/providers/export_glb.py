"""Mesh validation/visualization/export provider (PLY vertex RGB → linear COLOR_0 GLB)."""

from __future__ import annotations

from pathlib import Path

from studio.providers.base import ExportProvider


class VertexColorGlbExportProvider(ExportProvider):
    key = "vertex_color_glb"
    display_name = "PLY/GLB vertex-color exporter (trimesh + plyfile)"

    def info(self):
        base = super().info()
        base.update(
            formats=["PLY (원본 정점 색상)", "GLB (KHR_materials_unlit, linear COLOR_0)"],
            color_space="PLY sRGB uint8 → glTF linear float, round-trip checked",
        )
        return base

    def validate_and_preview(self, mesh, output=None):
        from studio.mesh import validate_mesh

        return validate_mesh(Path(mesh), Path(output) if output else None)
