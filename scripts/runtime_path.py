"""Resolve an external installed runtime or the preserved developer environment."""

import json, os
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = os.environ.get("STUDIO_RUNTIME")
if not path and (root / ".runtime/bin/python").is_file():
    path = str(root / ".runtime")
if not path:
    config = (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "m4ml-studio/install.json"
    )
    try:
        path = json.loads(config.read_text()).get("runtime")
    except (FileNotFoundError, ValueError):
        pass
print(path or root / ".runtime")
