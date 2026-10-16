"""Live Gaussian rendering through the 2DGS / SIBR remote-viewer protocol.

* Renderer process: ``studio.gaussian_render_server`` (original Object-Aware renderer, same
  wire protocol as ``view.py``), started by ``studio.live_render`` on a free loopback port.
* Client: ``studio.gaussian_protocol`` (what ``SIBR_remoteGaussian_app`` sends/receives).
* Optional external viewer: the bundled ``SIBR_remoteGaussian_app`` (runtime/sibr) can attach
  to the same renderer process (advanced menu only).

Everything engine-specific stays here; the API and UI see only the RenderingProvider contract.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import numpy as np

from studio.doctor import ROOT
from studio.providers.base import RenderingProvider

# Server render item → (mode key, Korean label). Only items the renderer really produces.
MODE_LABELS = {
    "RGB": ("rgb", "색상"),
    "Alpha": ("alpha", "불투명도"),
    "Normal": ("normal", "법선"),
    "Depth": ("depth", "깊이"),
    "ObjectMark": ("objectmark", "객체 점수"),
    "Edge": ("edge", "윤곽"),
    "Curvature": ("curvature", "곡률"),
}
GAUSSIAN_PROPS = {"opacity", "scale_0", "rot_0", "f_dc_0", "objectmark_score"}


def ply_header(path: Path) -> dict:
    """Element counts and vertex properties from a PLY header (no payload read)."""
    elements, props, current = {}, [], None
    with path.open("rb") as f:
        if f.readline().strip() != b"ply":
            raise ValueError("PLY 파일이 아닙니다.")
        for _ in range(4096):
            line = f.readline().decode("ascii", "replace").strip()
            if line == "end_header":
                return {"elements": elements, "vertex_props": props}
            parts = line.split()
            if parts[:1] == ["element"] and len(parts) == 3:
                current = parts[1]
                elements[current] = int(parts[2])
            elif parts[:1] == ["property"] and current == "vertex":
                props.append(parts[-1])
    raise ValueError("PLY 헤더가 손상되었습니다.")


def sibr_binary(configured=None):
    for path in (configured, os.environ.get("STUDIO_SIBR"), ROOT / "runtime/sibr/bin/SIBR_remoteGaussian_app"):
        if path and Path(path).is_file() and os.access(path, os.X_OK):
            return Path(path)
    return None


def missing_libraries(binary: Path) -> list[str]:
    try:
        out = subprocess.run(["ldd", str(binary)], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ["ldd"]
    return [line.split()[0] for line in out.splitlines() if "not found" in line]


class GaussianRemoteRenderingProvider(RenderingProvider):
    key = "gaussian_remote"
    display_name = "Object-Aware 2DGS renderer · 2DGS/SIBR remote-viewer protocol"

    def info(self):
        base = super().info()
        sibr = sibr_binary(self.options.get("sibr_binary"))
        build = {}
        if sibr:
            try:
                build = json.loads((sibr.parents[1] / "BUILD_INFO.json").read_text())
            except (OSError, ValueError):
                pass
        base.update(
            renderer="original gaussian_renderer.render (diff_surfel_rasterization, CUDA)",
            protocol="gaussian_renderer/network_gui.py (Gaussian-Splatting-Monitor / SIBR remote)",
            external_viewer=str(sibr) if sibr else None,
            external_viewer_commit=build.get("commit"),
            external_viewer_missing_libraries=missing_libraries(sibr) if sibr else None,
            license="Inria/GRAPHDECO non-commercial research and evaluation (renderer and SIBR)",
        )
        return base

    # ------------------------------------------------------------------ model
    def iterations(self, model: Path) -> list[int]:
        out = []
        for d in (model / "point_cloud").glob("iteration_*"):
            m = re.fullmatch(r"iteration_(\d+)", d.name)
            if m and (d / "point_cloud.ply").is_file():
                out.append(int(m.group(1)))
        return sorted(out)

    def locate_model(self, root, project, iteration=None):
        training = project.get("training") or {}
        scene = project.get("scene")
        if not training.get("path") or not scene:
            raise FileNotFoundError("3D 재구성 학습 결과가 아직 없습니다.")
        model = (root / training["path"]).resolve()
        source = (root / scene).resolve()
        if not model.is_relative_to(root.resolve()) or not source.is_relative_to(root.resolve()):
            raise ValueError("학습 결과 경로가 프로젝트 밖을 가리킵니다.")
        iterations = self.iterations(model)
        if not iterations:
            raise FileNotFoundError("학습된 Gaussian 파일(point_cloud.ply)을 찾지 못했습니다.")
        chosen = iteration if iteration in iterations else iterations[-1]
        ply = model / "point_cloud" / f"iteration_{chosen}" / "point_cloud.ply"
        header = ply_header(ply)
        missing = GAUSSIAN_PROPS - set(header["vertex_props"])
        if "face" in header["elements"] or missing:
            raise ValueError("선택한 파일은 학습된 Gaussian이 아닙니다 (메시이거나 속성이 누락됨).")
        count = header["elements"].get("vertex", 0)
        if not count:
            raise ValueError("학습 결과에 Gaussian이 없습니다.")
        cameras = self._cameras(model, source)
        return {
            "model": str(model), "source": str(source), "ply": str(ply),
            "iterations": iterations, "iteration": chosen, "gaussians": count,
            "ply_bytes": ply.stat().st_size, "cameras": cameras,
            "target": self._scene_center(source, cameras),
        }

    def _cameras(self, model: Path, source: Path) -> list[dict]:
        """Training cameras (cameras.json written by train.py), checked against this scene."""
        try:
            raw = json.loads((model / "cameras.json").read_text())
        except (OSError, ValueError):
            return []
        names = {p.stem for p in (source / "images").iterdir()} if (source / "images").is_dir() else set()
        out = []
        for c in raw:
            if names and c.get("img_name") not in names:
                raise ValueError("학습 결과의 카메라가 이 프로젝트의 사진과 일치하지 않습니다.")
            out.append({
                "name": c["img_name"], "position": c["position"], "rotation": c["rotation"],
                "width": c["width"], "height": c["height"], "fy": c["fy"], "fx": c["fx"],
            })
        return sorted(out, key=lambda c: c["name"])

    def _scene_center(self, source: Path, cameras: list[dict]):
        """Orbit target: median of the sparse SfM points (robust to stray points)."""
        try:
            from studio.colmap import loader

            reader = loader()
            xyz, _, _ = reader.read_points3D_binary(str(source / "sparse/0/points3D.bin"))
            if len(xyz):
                return [float(v) for v in np.median(np.asarray(xyz), axis=0)]
        except Exception:
            pass
        if cameras:
            return [float(v) for v in np.mean([c["position"] for c in cameras], axis=0)]
        return [0.0, 0.0, 0.0]

    # ------------------------------------------------------------------ process / protocol
    def server_command(self, model):
        return [sys.executable, "-m", "studio.gaussian_render_server", "--model", model["model"],
                "--source", model["source"], "--iteration", str(model["iteration"]), "--port", "0"]

    def connect(self, port):
        from studio.gaussian_protocol import RemoteRendererClient

        return RemoteRendererClient("127.0.0.1", port, timeout=30)

    def render(self, client, camera):
        from studio.gaussian_protocol import camera_message

        view = np.asarray(camera["view"], dtype=np.float64).reshape(4, 4).T  # column-major in
        width, height = int(camera["width"]), int(camera["height"])
        mode = int(camera.get("mode_index", 0))
        message = camera_message(view, width, height, float(camera["fovy"]),
                                 float(camera.get("znear", 0.01)), float(camera.get("zfar", 1000.0)),
                                 render_mode=mode, scaling_modifier=float(camera.get("scaling", 1.0)))
        rgb, _, metrics = client.request(message)
        return rgb, metrics

    def modes(self, server_items):
        order = ["RGB", "Alpha", "Depth", "Normal", "ObjectMark"]
        return [{"key": MODE_LABELS[name][0], "label": MODE_LABELS[name][1], "index": server_items.index(name)}
                for name in order if name in server_items]

    def external_viewer_command(self, port, model):
        sibr = sibr_binary(self.options.get("sibr_binary"))
        if not sibr or missing_libraries(sibr):
            return None
        return [str(sibr), "-s", model["source"], "--ip", "127.0.0.1", "--port", str(port)]
