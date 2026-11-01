"""Operator tool. There is deliberately no HTTP admin endpoint: run this over SSH on the
server, as the service account (e.g. `sudo -u m4ml-web env $(cat /etc/m4ml-web/gateway.env) ...`).

  python -m studio_web.admin status
  python -m studio_web.admin maintenance on|off        # research mode: no new GPU work
  python -m studio_web.admin delete-session <id>       # stop and delete one workspace
  python -m studio_web.admin backup <file>             # consistent copy of gateway.sqlite
  python -m studio_web.admin audit [n]                 # last n audit events (no secrets)
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import time

from studio_web import config as config_module
from studio_web.auth.slots import Slots
from studio_web.persistence.db import Database
from studio_web.runtime.backends import Backends
from studio_web.runtime.gpu_leases import GpuLeases, gpu_device
from studio_web.services import retention


def _context():
    cfg = config_module.load()
    db = Database(cfg.database)
    return cfg, db, Backends(cfg, db), Slots(db, cfg.max_active_sessions)


def status() -> dict:
    cfg, db, backends, slots = _context()
    with db.connect() as conn:
        sessions = conn.execute("SELECT state, COUNT(*) AS n FROM sessions GROUP BY state").fetchall()
        queue = conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
        lease = conn.execute("SELECT session_id, kind, state, started FROM gpu_leases WHERE state IN ('allocating','running','releasing')").fetchone()
        waiting = conn.execute("SELECT COUNT(*) FROM gpu_leases WHERE state='queued'").fetchone()[0]
    usage = shutil.disk_usage(cfg.home)
    return {
        "schema_version": db.version(),
        "sessions": {r["state"]: r["n"] for r in sessions},
        "active_slots": slots.active_count(), "max_active": cfg.max_active_sessions, "waiting_room": queue,
        "gpu_owner": dict(lease) if lease else None, "gpu_queue": waiting,
        "maintenance": (cfg.home / "maintenance").exists(),
        "disk_free_gib": round(usage.free / 2**30, 1),
    }


def maintenance(on: bool):
    cfg = config_module.load()
    flag = cfg.home / "maintenance"
    if on:
        flag.touch()
    elif flag.exists():
        flag.unlink()
    return {"maintenance": flag.exists()}


def delete_session(session_id: str):
    cfg, db, backends, slots = _context()
    GpuLeases(db, cfg.gpu_lock_dir, gpu_device(), cfg.home / "maintenance").drop_session(session_id)
    return {"deleted": retention.delete_session(db, backends, slots, session_id)}


def backup(target: str):
    """SQLite online backup (consistent while the gateway runs), then an integrity check."""
    cfg = config_module.load()
    source = sqlite3.connect(cfg.database)
    dest = sqlite3.connect(target)
    with dest:
        source.backup(dest)
    ok = dest.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    source.close(); dest.close()
    return {"backup": target, "integrity": ok, "at": time.time()}


def audit(n: int = 50):
    cfg = config_module.load()
    db = Database(cfg.database)
    with db.connect() as conn:
        rows = conn.execute("SELECT at, session_id, event FROM audit ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    return [{"at": r["at"], "session": (r["session_id"] or "")[:8], "event": r["event"]} for r in rows]


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__); return 2
    cmd, args = argv[0], argv[1:]
    if cmd == "status":
        out = status()
    elif cmd == "maintenance" and args in (["on"], ["off"]):
        out = maintenance(args[0] == "on")
    elif cmd == "delete-session" and len(args) == 1:
        out = delete_session(args[0])
    elif cmd == "backup" and len(args) == 1:
        out = backup(args[0])
    elif cmd == "audit" and len(args) <= 1:
        out = audit(int(args[0]) if args else 50)
    else:
        print(__doc__); return 2
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
