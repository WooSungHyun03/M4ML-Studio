"""Engine configuration, discovery and the provider registry.

Users never pick engines in the default UI. The configuration below says which
implementation backs each capability; replacing an engine means registering a new
provider class and changing ``provider`` here (or in the user settings file), with
no UI or orchestrator change.

Resolution order for every option: user settings (``engines`` section) → environment
override (documented per option) → built-in default.
"""

from __future__ import annotations

import copy
import functools
import os
from pathlib import Path
import re
import shutil
import subprocess

from studio.doctor import ROOT

ENGINE_SCHEMA_VERSION = 1

DEFAULTS = {
    "schema_version": ENGINE_SCHEMA_VERSION,
    "camera": {
        "provider": "colmap",
        "options": {
            # None → bundled runtime/colmap → install runtime → PATH (in that order)
            "binary": None,
            "use_gpu": True,
            # CPU fallback is never silent: a job must explicitly request it.
            "allow_cpu_fallback": False,
            # None → all CPU cores up to 16 (mapper/bundle adjustment are CPU-bound)
            "num_threads": None,
        },
    },
    "segmentation": {
        "provider": "sam31",
        "options": {"checkpoint": None, "session_idle_seconds": 600},
    },
    "training": {"provider": "object_aware_2dgs", "options": {"iterations": 30000}},
    "mesh": {"provider": "object_aware_tsdf", "options": {"mesh_res": 1024}},
    "export": {"provider": "vertex_color_glb", "options": {}},
    # Live view of the trained Gaussians; sibr_binary None → bundled runtime/sibr.
    "rendering": {"provider": "gaussian_remote", "options": {"sibr_binary": None, "idle_seconds": 300}},
}


def _merge(base, extra):
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def config():
    from studio.config import settings

    return _merge(DEFAULTS, settings().get("engines"))


def registry():
    # Imported lazily so the API process never imports torch / CUDA modules.
    from studio.providers.camera_colmap import ColmapCameraProvider
    from studio.providers.segmentation_sam31 import Sam31SegmentationProvider
    from studio.providers.training_object_aware import ObjectAwareTrainingProvider
    from studio.providers.mesh_tsdf import ObjectAwareTSDFMeshProvider
    from studio.providers.export_glb import VertexColorGlbExportProvider
    from studio.providers.render_gaussian_remote import GaussianRemoteRenderingProvider

    return {
        "camera": {"colmap": ColmapCameraProvider},
        "segmentation": {"sam31": Sam31SegmentationProvider},
        "training": {"object_aware_2dgs": ObjectAwareTrainingProvider},
        "mesh": {"object_aware_tsdf": ObjectAwareTSDFMeshProvider},
        "export": {"vertex_color_glb": VertexColorGlbExportProvider},
        "rendering": {"gaussian_remote": GaussianRemoteRenderingProvider},
    }


def provider(capability):
    cfg = config()[capability]
    classes = registry()[capability]
    if cfg["provider"] not in classes:
        raise ValueError(f"설정된 처리 엔진을 찾을 수 없습니다: {capability}")
    return classes[cfg["provider"]](cfg.get("options"))


def all_info():
    out = {}
    for capability in ("camera", "segmentation", "training", "mesh", "export", "rendering"):
        try:
            out[capability] = provider(capability).info()
        except Exception as exc:  # diagnostics must never break the app
            out[capability] = {"capability": capability, "error": str(exc)}
    return out


# --------------------------------------------------------------------------- COLMAP discovery
def _install_runtime():
    import json

    cfg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "m4ml-studio/install.json"
    try:
        return json.loads(cfg.read_text()).get("colmap")
    except (FileNotFoundError, ValueError):
        return None


def colmap_candidates(configured=None):
    """Ordered (path, origin) candidates. The bundled build always wins over PATH."""
    seen, out = set(), []
    for path, origin in (
        (configured, "settings"),
        (os.environ.get("STUDIO_COLMAP"), "environment"),
        (ROOT / "runtime/colmap/bin/colmap", "bundled"),
        (_install_runtime(), "installed"),
        (shutil.which("colmap"), "system"),
    ):
        if not path:
            continue
        path = Path(path).expanduser()
        if path.is_file() and os.access(path, os.X_OK) and path.resolve() not in seen:
            seen.add(path.resolve())
            out.append((path, origin))
    return out


@functools.lru_cache(maxsize=8)
def _probe(path: str, mtime: float):
    try:
        done = subprocess.run([path, "help"], capture_output=True, text=True, timeout=30)
        text = done.stdout + "\n" + done.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    version = re.search(r"COLMAP\s+([\w.\-]+)", text)
    commit = re.search(r"Commit\s+([0-9a-fA-F]+|Unknown)", text)
    cuda = re.search(r"with(out)?\s+CUDA", text)
    return {
        "ok": bool(version),
        "version": version[1] if version else None,
        "commit": commit[1] if commit else None,
        "cuda": bool(cuda and not cuda[1]),
        "banner": text.strip().splitlines()[0] if text.strip() else "",
    }


def colmap_binary(configured=None, require_cuda=False):
    """Best usable COLMAP. Returns (path, probe, origin) or raises a user-facing error."""
    candidates = colmap_candidates(configured)
    probed = [(p, _probe(str(p.resolve()), p.stat().st_mtime), origin) for p, origin in candidates]
    usable = [c for c in probed if c[1].get("ok")]
    if require_cuda:
        usable = [c for c in usable if c[1].get("cuda")]
    if not usable:
        if require_cuda and any(c[1].get("ok") for c in probed):
            raise RuntimeError(
                "GPU 가속을 지원하는 카메라 정합 엔진을 찾지 못했습니다. "
                "설치 폴더에서 ./scripts/build_colmap.sh 로 GPU 엔진을 빌드하거나, "
                "CPU로 실행하도록 명시적으로 선택하세요."
            )
        raise RuntimeError(
            "카메라 정합 엔진을 찾을 수 없습니다. ./scripts/build_colmap.sh 로 설치하세요."
        )
    return usable[0]


@functools.lru_cache(maxsize=32)
def colmap_options(path: str, mtime: float, command: str):
    """Option names accepted by THIS binary's ``<command> -h`` (no guessing across versions)."""
    try:
        done = subprocess.run(
            [path, command, "-h"], capture_output=True, text=True, timeout=30
        )
        # COLMAP prints usage to stdout or stderr depending on version/log target.
        text = done.stdout + "\n" + done.stderr
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    return frozenset(re.findall(r"--([A-Za-z_]+\.[A-Za-z_]+|[A-Za-z_]+)", text))


def pick_option(binary: Path, command: str, *names):
    available = colmap_options(str(binary.resolve()), binary.stat().st_mtime, command)
    for name in names:
        if name in available:
            return "--" + name
    return None


def read_build_info(binary: Path):
    import json

    for candidate in (binary.resolve().parent.parent / "BUILD_INFO.json",):
        try:
            return json.loads(candidate.read_text())
        except (FileNotFoundError, ValueError):
            pass
    return None
