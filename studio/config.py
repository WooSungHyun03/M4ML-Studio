"""User settings (XDG config) with an explicit schema version and forward migration.

Layers
  * built-in defaults           — studio.engines.DEFAULTS, training defaults
  * user settings  (this file)  — ~/.config/m4ml-studio/settings.json
  * project settings            — stored in each project document (``settings``)
  * environment overrides       — STUDIO_* variables (documented in docs/ARCHITECTURE.md)

Migration never drops data: before a schema upgrade the previous file is copied to
``settings.v<old>.json`` next to it.
"""

import json, os, shutil
from pathlib import Path
from studio.doctor import atomic_json, ROOT

from studio import __version__

VERSION = __version__
SETTINGS_SCHEMA = 2


def config_path():
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "m4ml-studio/settings.json"
    )


def migrate(data):
    """Return settings upgraded to SETTINGS_SCHEMA (pure function, tested)."""
    data = dict(data or {})
    version = int(data.get("schema_version", 1))
    if version < 2:
        # v1 kept a flat "checkpoint" key for the segmentation model.
        engines = data.setdefault("engines", {})
        if data.get("checkpoint"):
            engines.setdefault("segmentation", {}).setdefault("options", {}).setdefault(
                "checkpoint", data["checkpoint"]
            )
        version = 2
    data["schema_version"] = version
    return data


def settings():
    path = config_path()
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {"schema_version": SETTINGS_SCHEMA}
    if int(data.get("schema_version", 1)) < SETTINGS_SCHEMA:
        backup = path.with_name(f"settings.v{data.get('schema_version', 1)}.json")
        if not backup.exists():
            shutil.copy2(path, backup)
        data = migrate(data)
        try:
            atomic_json(path, data)
        except OSError:
            pass  # read-only config dir: use migrated values in memory
    return data


def save_settings(update):
    current = settings()

    def deep(a, b):
        for key, value in b.items():
            if isinstance(value, dict) and isinstance(a.get(key), dict):
                deep(a[key], value)
            else:
                a[key] = value

    deep(current, update)
    current["schema_version"] = SETTINGS_SCHEMA
    config_path().parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_json(config_path(), current)
    return current


def checkpoint_path():
    data = settings()
    configured = (
        os.environ.get("STUDIO_SAM_CHECKPOINT")
        or data.get("engines", {}).get("segmentation", {}).get("options", {}).get("checkpoint")
        or data.get("checkpoint")
        or ROOT / "models/sam3.1/sam3.1_multiplex.pt"
    )
    return Path(configured).expanduser().resolve()
