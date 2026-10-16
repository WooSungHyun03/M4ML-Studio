"""Capability contracts shared by the pipeline, the API and every engine adapter.

The UI and the job orchestrator only speak these capability interfaces and data
contracts. Concrete engines (COLMAP, SAM 3.1, Object-Aware 2DGS, TSDF, ...) live in
sibling modules and are chosen through ``studio.engines`` configuration, so an engine
can be replaced without touching the UI or the project/stage bookkeeping.

Execution contract (all providers)
----------------------------------
* Long-running methods run inside the worker process (never the API thread) and get a
  :class:`JobContext`. They must poll ``ctx.cancel`` (or run external programs through
  ``ctx.run`` which already does) and raise :class:`studio.process.Cancelled` when asked.
* Progress is reported only through ``ctx.progress(message, current=None, total=None)``.
* Errors raised to the caller are user-presentable Korean ``ValueError``/``RuntimeError``
  messages; tracebacks go to the job log, never to the default UI.
* GPU work happens in a child process selected by ``ctx.env['CUDA_VISIBLE_DEVICES']``;
  the orchestrator holds the per-device lock, providers never pick a device themselves.
* Providers do not mutate the project document. They return data contracts; the
  orchestrator (``studio.worker``) records them and invalidates downstream stages.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import sys
import threading
from typing import Callable, Iterable, Optional

from studio.process import run as run_process

DATA_CONTRACT_VERSION = 1


# --------------------------------------------------------------------------- contracts
@dataclass
class RegisteredImageSet:
    """Undistorted images that have a camera pose in ONE consistent reconstruction.

    ``coordinate_system`` documents the pixel frame every downstream artifact (masks,
    clicks, training images) must use: undistorted PINHOLE pixels of ``scene/images``.
    """

    scene: str  # project-relative scene directory (images/, sparse/0/)
    names: list[str]
    coordinate_system: str = "colmap-undistorted-pinhole-pixels"
    source: str = "computed"  # computed | imported
    version: int = DATA_CONTRACT_VERSION


@dataclass
class CameraReport:
    """Per-image diagnostics. Matching success and pose registration are separate facts."""

    images: list[dict]
    verified_pairs: Optional[int]
    registered: int
    total: int
    matched: Optional[int]
    selected_component: Optional[str] = None
    components: dict = field(default_factory=dict)
    engine: dict = field(default_factory=dict)  # name/version/gpu-used per step
    version: int = DATA_CONTRACT_VERSION

    def to_dict(self):
        return asdict(self)


@dataclass
class MaskResult:
    """One binary mask aligned with a registered image (uint8, 0/255, same size)."""

    name: str
    valid: bool
    path: Optional[str] = None
    area: Optional[int] = None
    coverage: Optional[float] = None
    sha256: Optional[str] = None
    size: Optional[list] = None
    warnings: list = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class TrainingProgress:
    iteration: int
    total: int
    loss: Optional[float] = None


@dataclass
class TrainingResult:
    path: str  # model directory (project relative)
    iterations: int
    gaussians: int
    checkpoint: Optional[str] = None
    resumed_from: Optional[int] = None


@dataclass
class MeshArtifact:
    path: str  # directory containing the exported mesh + preview
    vertices: int
    triangles: int
    colors: bool
    sha256: str
    extra: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- job context
class JobContext:
    """Everything a provider may use while running inside the worker process."""

    def __init__(
        self,
        *,
        root: Path,
        output: Path,
        log: Path,
        env: dict,
        cancel: threading.Event,
        progress: Callable[..., None],
        cwd: Path,
        on_line: Optional[Callable[[str], None]] = None,
    ):
        self.root, self.output, self.log = Path(root), Path(output), Path(log)
        self.env, self.cancel, self._progress = env, cancel, progress
        self.cwd, self.on_line = Path(cwd), on_line

    def progress(self, message, current=None, total=None):
        self._progress(message, current, total)

    def run(self, argv: Iterable, *, timeout=86400, on_line=None, env=None):
        """Run an external program with literal argv, cancellation and durable logging."""
        run_process(
            list(argv),
            self.log,
            cwd=self.cwd,
            env=env or self.env,
            cancel=self.cancel,
            timeout=timeout,
            on_line=on_line or self.on_line,
        )

    def python(self, args: Iterable, **kwargs):
        """Run a module/script with the same private runtime as the worker."""
        self.run([sys.executable, *args], **kwargs)

    def relative(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.root.resolve()).as_posix()


# --------------------------------------------------------------------------- interfaces
class Provider:
    """Common identity/diagnostic surface shown only in the advanced information panel."""

    capability = ""  # camera | segmentation | training | mesh | export
    key = ""  # registry key used in engine configuration
    display_name = ""  # technical engine name (advanced UI only)

    def __init__(self, options: Optional[dict] = None):
        self.options = dict(options or {})

    def info(self) -> dict:
        """Version, paths, verification state and license of the engine."""
        return {"capability": self.capability, "key": self.key, "name": self.display_name}

    def requires_gpu(self, request: dict) -> bool:
        return True


class CameraProvider(Provider):
    capability = "camera"

    def reconstruct(self, ctx: JobContext, images: Path, work: Path, request: dict) -> dict:
        """Features → matching → poses → undistortion. Returns a CameraReport dict whose
        ``scene`` contains ONLY images registered in the selected component."""
        raise NotImplementedError

    def select_component(self, ctx: JobContext, images: Path, previous: Path, work: Path, component: str) -> dict:
        raise NotImplementedError

    def validate_scene(self, scene: Path) -> set:
        raise NotImplementedError


class SegmentationProvider(Provider):
    """Interactive object selection (``predict``) and multi-view propagation."""

    capability = "segmentation"

    def predict(self, ctx: JobContext, request: dict) -> dict:
        """One reference image + positive/negative pixel points → one mask (preview)."""
        raise NotImplementedError

    def propagate(self, ctx: JobContext, request: dict) -> dict:
        """Masks for registered views, starting from the confirmed reference prompt."""
        raise NotImplementedError

    def session_command(self) -> list[str]:
        """argv for a persistent interactive session process (model kept loaded)."""
        raise NotImplementedError


class TrainingProvider(Provider):
    capability = "training"

    def validate_dataset(self, scene: Path, masks: dict) -> list[dict]:
        raise NotImplementedError

    def train(self, ctx: JobContext, scene: Path, model: Path, request: dict) -> dict:
        raise NotImplementedError

    def parse_progress(self, line: str) -> Optional[TrainingProgress]:
        return None

    def checkpoints(self, model: Path) -> list[int]:
        return []


class MeshProvider(Provider):
    capability = "mesh"

    def extract(self, ctx: JobContext, scene: Path, model: Path, iterations: int, output: Path, request: dict) -> dict:
        raise NotImplementedError


class ExportProvider(Provider):
    capability = "export"

    def validate_and_preview(self, mesh: Path, output: Optional[Path] = None) -> dict:
        raise NotImplementedError

    def requires_gpu(self, request):
        return False
