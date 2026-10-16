"""Capability providers. See ``studio/providers/base.py`` for the contracts and
``studio/engines.py`` for configuration and the registry."""

from studio.providers.base import (  # noqa: F401
    CameraProvider,
    ExportProvider,
    JobContext,
    MeshProvider,
    SegmentationProvider,
    TrainingProvider,
)
