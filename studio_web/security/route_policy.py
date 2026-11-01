"""Public route policy for the web gateway: method + normalised path template, default deny.

Every route of the desktop backend (`studio.api.app`) has exactly one entry in ROUTES; the
contract test fails when a backend route is added without a decision. `match()` is the only
way the gateway decides whether a browser request may reach a session backend.

Classes
  PROXY     forwarded to the caller's own session backend (ownership is the session→backend
            mapping: a project id from another session does not exist in that backend).
  GATEWAY   handled by a gateway endpoint instead (upload pipeline, hard delete, about).
  INTERNAL  called only by the gateway itself, never on behalf of a browser request.
  DENY      never reachable from the web (server paths, process control, host details).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import unquote


class Access(str, Enum):
    PROXY = "proxy"
    GATEWAY = "gateway"
    INTERNAL = "internal"
    DENY = "deny"


@dataclass(frozen=True)
class Route:
    method: str
    template: str
    access: Access
    reason: str
    gpu: bool = False  # starts or holds GPU work: must pass the GPU scheduler (Phase 3)
    response_filter: str | None = None  # name of the response filter (server paths removed)
    grammar: tuple[tuple[str, str], ...] = ()  # parameter -> SEGMENT_PATTERNS key, if not the same


# Path parameter grammar. Anything else is rejected before a template is even compared.
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
SEGMENT_PATTERNS = {
    "project_id": UUID,
    "job_id": UUID,
    "artifact_id": UUID + r"|training",
    "name": r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}",  # image / mask names (000001.png)
    "group": r"camera|segmentation|review|training|mesh|view",
    "stage": r"colmap|preview|sam|train|mesh",
    "component_id": r"[a-z0-9][a-z0-9._-]{0,63}",
    "help_name": r"quickstart|guide|troubleshooting|shortcuts",
}
# Project files a browser may load: images, masks and meshes only (no logs, JSON, checkpoints).
FILE_PATH = r"(?:[A-Za-z0-9][A-Za-z0-9._-]{0,127}/){0,8}[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.(?:png|jpg|jpeg|ply|glb)"

P = Access.PROXY
G = Access.GATEWAY
I = Access.INTERNAL
D = Access.DENY

ROUTES: tuple[Route, ...] = (
    Route("GET", "/api/session", D, "returns the backend token to any caller outside desktop mode"),
    Route("GET", "/api/health", G, "GPU UUIDs, runtime path; the gateway answers with a summary"),
    Route("GET", "/api/engines", G, "engine paths and configuration; the gateway answers with the licence list only"),
    Route("GET", "/api/license-text/{component_id}", P, "shipped licence texts"),
    Route("PUT", "/api/settings/checkpoint", D, "sets a server file path as the model"),
    Route("POST", "/api/shutdown", D, "terminates the backend process"),
    Route("GET", "/api/diagnostics", D, "host details; administrators only"),
    Route("GET", "/api/projects", P, "the session's own projects", response_filter="project_list"),
    Route("POST", "/api/projects", P, "new project (gateway enforces the project quota)"),
    Route("GET", "/api/projects/{project_id}", P, "project document", response_filter="project"),
    Route("PATCH", "/api/projects/{project_id}", P, "rename"),
    Route("DELETE", "/api/projects/{project_id}", G, "desktop archives; the web deletes files for real"),
    Route("POST", "/api/projects/{project_id}/restore", D, "archive restore is not a web concept"),
    Route("POST", "/api/projects/{project_id}/purge", G, "web deletion; the gateway cancels running work first"),
    Route("POST", "/api/projects/{project_id}/images", G, "photos go through the gateway upload pipeline"),
    Route("POST", "/api/projects/{project_id}/import-complete", P, "finishes import, starts camera registration", gpu=True),
    Route("POST", "/api/projects/{project_id}/import-files", D, "COLMAP/mask import is outside the web MVP"),
    Route("POST", "/api/projects/{project_id}/inspect-import", D, "COLMAP/mask import is outside the web MVP"),
    Route("POST", "/api/projects/{project_id}/commit-import", D, "COLMAP/mask import is outside the web MVP"),
    Route("POST", "/api/projects/{project_id}/mesh-file", D, "untrusted mesh parsing is outside the web MVP"),
    Route("POST", "/api/scan-folder", D, "reads an arbitrary server folder"),
    Route("POST", "/api/projects/from-folder", D, "copies an arbitrary server folder"),
    Route("POST", "/api/projects/{project_id}/result-artifacts/{artifact_id}/activate", P, "choose a result produced in this project"),
    Route("GET", "/api/projects/{project_id}/assets", P, "checkpoint and mesh file list", response_filter="assets"),
    Route("GET", "/api/projects/{project_id}/live-render", P, "live viewport availability"),
    Route("POST", "/api/projects/{project_id}/live-render/start", P, "starts the GPU renderer", gpu=True),
    Route("POST", "/api/projects/{project_id}/live-render/frame", P, "one rendered frame", gpu=True),
    Route("POST", "/api/projects/{project_id}/live-render/stop", P, "releases the renderer"),
    Route("POST", "/api/projects/{project_id}/live-render/external", D, "opens a native window on the server"),
    Route("GET", "/api/projects/{project_id}/sparse-points", P, "sparse point cloud for the viewer"),
    Route("GET", "/api/help/{name}", P, "shipped help documents", grammar=(("name", "help_name"),)),
    Route("GET", "/api/about", G, "exposes install and data paths; gateway answers instead"),
    Route("GET", "/api/gpu-monitor", G, "host process ids and command lines; the gateway answers with GPU load only"),
    Route("POST", "/api/projects/{project_id}/duplicate", D, "unbounded disk copy; outside the web MVP"),
    Route("DELETE", "/api/projects/{project_id}/images/{name}", P, "remove a photo before registration"),
    Route("GET", "/api/projects/{project_id}/task-settings", P, "stage settings"),
    Route("PATCH", "/api/projects/{project_id}/task-settings/{group}", P, "save stage settings (gateway validates web limits)"),
    Route("GET", "/api/projects/{project_id}/preflight", P, "training preflight"),
    Route("POST", "/api/projects/{project_id}/jobs/{stage}", P, "start a stage job", gpu=True),
    Route("POST", "/api/projects/{project_id}/prompt-session", P, "open the object-selection session"),
    Route("POST", "/api/projects/{project_id}/prompt", P, "one object-selection click", gpu=True),
    Route("POST", "/api/projects/{project_id}/selection/warmup", P, "load the selection model", gpu=True),
    Route("POST", "/api/projects/{project_id}/cancel", P, "cancel the running job"),
    Route("PUT", "/api/projects/{project_id}/masks/{name}", P, "save or approve a mask"),
    Route("POST", "/api/projects/{project_id}/skip-review", P, "skip the remaining review"),
    Route("GET", "/api/projects/{project_id}/files/{path:path}", P, "images, masks and meshes of the project only"),
    Route("GET", "/api/projects/{project_id}/events", P, "progress events (SSE)"),
    Route("GET", "/api/projects/{project_id}/logs/{job_id}", G, "raw logs contain server paths; the gateway redacts them"),
    Route("GET", "/api/projects/{project_id}/training-metrics/{job_id}", P, "parsed training curve"),
)

def _compile(route: Route) -> re.Pattern:
    grammar = dict(route.grammar)
    out = []
    for piece in re.split(r"(\{[^}]+\})", route.template):
        if piece.startswith("{"):
            key = piece[1:-1]
            if key == "path:path":
                out.append(f"(?P<path>{FILE_PATH})")
            else:
                out.append(f"(?P<{key}>{SEGMENT_PATTERNS[grammar.get(key, key)]})")
        else:
            out.append(re.escape(piece))
    return re.compile("".join(out))


_COMPILED = [(route, _compile(route)) for route in ROUTES]


class Rejected(ValueError):
    """The request path or method is not allowed; the gateway answers 404 without detail."""


def normalise(raw_path: str) -> str:
    """Decode a raw request path exactly once and refuse every ambiguous form.

    Rejected: encoded '/', '\\', '.', '%' (double encoding), NUL and control characters,
    backslashes, empty, '.' or '..' segments, trailing slashes, non-ASCII, query strings.
    """
    if not raw_path.startswith("/") or len(raw_path) > 2048 or "?" in raw_path or "#" in raw_path:
        raise Rejected("path")
    if re.search(r"%(2[eEfF]|5[cC]|25|00|[01][0-9a-fA-F]|7[fF])", raw_path):
        raise Rejected("encoded separator or double encoding")
    try:
        path = unquote(raw_path, errors="strict")
    except UnicodeDecodeError as exc:
        raise Rejected("encoding") from exc
    if not path.isascii() or any(ord(c) < 0x20 or ord(c) == 0x7F for c in path) or "\\" in path:
        raise Rejected("characters")
    segments = path.split("/")[1:]
    if any(s in ("", ".", "..") for s in segments):
        raise Rejected("segments")
    return path


def match(method: str, raw_path: str) -> tuple[Route, dict[str, str]]:
    """Return the allowed backend route for a browser request or raise Rejected."""
    path = normalise(raw_path)
    method = method.upper()
    for route, pattern in _COMPILED:
        found = pattern.fullmatch(path)
        if found and route.method == method:
            if route.access is not Access.PROXY:
                raise Rejected(route.access.value)
            return route, found.groupdict()
    raise Rejected("no route")
