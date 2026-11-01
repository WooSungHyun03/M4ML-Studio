"""Remove server paths from anything a browser receives."""

from __future__ import annotations

import re
from typing import Any

# Keys that only ever hold server paths or host details.
PATH_KEYS = frozenset({"project_path", "source_path", "source_folder", "runtime", "runtime_path",
                       "data", "install_root", "uuid", "gpu_uuid", "log_path", "work"})
# An absolute POSIX path with at least two components (e.g. /home/x/..., /srv/m4ml-web/...).
_ABSOLUTE = re.compile(r"(?<![\w.:/])/(?:[^\s/\"'<>:]+/)+[^\s\"'<>:]*")
PLACEHOLDER = "[서버 경로]"


def text(value: str) -> str:
    return _ABSOLUTE.sub(PLACEHOLDER, value)


def value(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: value(v) for k, v in obj.items() if k not in PATH_KEYS}
    if isinstance(obj, list):
        return [value(v) for v in obj]
    if isinstance(obj, str):
        return text(obj)
    return obj


def contains_path(obj: Any) -> bool:
    if isinstance(obj, dict):
        return any(k in PATH_KEYS or contains_path(v) for k, v in obj.items())
    if isinstance(obj, list):
        return any(contains_path(v) for v in obj)
    return isinstance(obj, str) and bool(_ABSOLUTE.search(obj))
