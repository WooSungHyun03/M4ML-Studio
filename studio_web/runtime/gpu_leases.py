"""GPU leases: which web session may use the RTX 4080 now (one at a time).

Lock ordering (ADR-WEB-003): the gateway never takes or waits on the GPU's fcntl lock. It
only decides which session's GPU request is forwarded; the backend's worker (or SAM /
renderer session) takes the existing `studio.gpu_lock` exactly as on the desktop. Because
only the lease holder's requests reach a backend, a worker waits on fcntl only when
something outside the web service (the desktop app) holds the GPU — never on another
web session, so the two layers cannot wait on each other.

A lease is released only after verified teardown: the holder's backend reports no
running stage *and* the device lock file can be taken (and is immediately let go). A
heartbeat or a "completed" job record alone is not proof that the GPU is free.

Batch work (registration, propagation, training + its automatic mesh) queues FIFO, one
queued request per session, and is started by the gateway when the GPU frees up.
Interactive work (object-selection clicks, the live renderer) is never queued: it gets
the GPU now or a clear "busy" answer.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from studio_web.persistence.db import Database

HOLDING = ("allocating", "running", "releasing")
BATCH_TEMPLATES = ("/api/projects/{project_id}/jobs/{stage}", "/api/projects/{project_id}/import-complete")
BATCH_MAX_SECONDS = 60 * 60  # soft limit for one batch lease (training stops at its last checkpoint)
DAILY_BATCH_SECONDS = 2 * 60 * 60  # per session per day (T04: a 100-photo run is ~20 min at 7k iterations)


@dataclass(frozen=True)
class Grant:
    status: str  # "granted" | "queued" | "busy"
    lease_id: str | None = None
    position: int | None = None
    reason: str = ""
    new: bool = False  # this call created the holding lease


def kind_of(template: str) -> str:
    return "batch" if template in BATCH_TEMPLATES else "interactive"


def device_lock_free(lock_dir: Path, device: str) -> bool:
    """Probe the shared fcntl lock without waiting: take it and let it go at once."""
    path = Path(lock_dir) / (hashlib.sha256(str(device).encode()).hexdigest() + ".lock")
    try:
        handle = path.open("a")
    except PermissionError:
        handle = path.open("r")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle, fcntl.LOCK_UN)
        return True
    except BlockingIOError:
        return False
    finally:
        handle.close()


def gpu_device() -> str:
    """The GPU id the backends use for their lock (nvidia-smi UUID of GPU 0)."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10, check=True).stdout.split()
        return out[0] if out else "0"
    except (OSError, subprocess.SubprocessError, IndexError):
        return "0"


def gpu_processes() -> list[int]:
    try:
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10, check=True).stdout
        return [int(x) for x in out.split() if x.strip().isdigit()]
    except (OSError, subprocess.SubprocessError):
        return []


class GpuLeases:
    def __init__(self, db: Database, lock_dir: Path, device: str, maintenance_flag: Path):
        self.db, self.lock_dir, self.device, self.maintenance_flag = db, Path(lock_dir), device, Path(maintenance_flag)
        self.lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    # ---- queries ---------------------------------------------------------------------
    def owner(self) -> dict | None:
        with self.db.connect() as db:
            row = db.execute(f"SELECT * FROM gpu_leases WHERE state IN {HOLDING}").fetchone()
        return dict(row) if row else None

    def queue(self) -> list[dict]:
        with self.db.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM gpu_leases WHERE state='queued' ORDER BY created, rowid")]

    def status_for(self, session_id: str) -> dict:
        owner, queue = self.owner(), self.queue()
        mine = next((i for i, q in enumerate(queue) if q["session_id"] == session_id), None)
        return {
            "holding": bool(owner and owner["session_id"] == session_id),
            "busy": bool(owner and owner["session_id"] != session_id),
            "queued_position": None if mine is None else mine + 1,
            "maintenance": self.maintenance_flag.exists(),
        }

    def batch_seconds_today(self, session_id: str, now: float | None = None) -> float:
        now = time.time() if now is None else now
        with self.db.connect() as db:
            rows = db.execute("SELECT started, ended FROM gpu_leases WHERE session_id=? AND kind='batch' AND started IS NOT NULL "
                              "AND (ended IS NULL OR ended > ?)", (session_id, now - 86400)).fetchall()
        return sum((r["ended"] or now) - max(r["started"], now - 86400) for r in rows)

    # ---- decisions ---------------------------------------------------------------------
    def request(self, session_id: str, project_id: str, template: str, route: str, body: bytes | None,
                external_busy: bool = False, now: float | None = None) -> Grant:
        now = time.time() if now is None else now
        kind = kind_of(template)
        with self.db.connect(immediate=True) as db:
            owner = db.execute(f"SELECT * FROM gpu_leases WHERE state IN {HOLDING}").fetchone()
            if owner and owner["session_id"] == session_id:
                if kind == "batch" and external_busy:
                    return Grant("busy", reason="external")  # heavy work never starts beside the desktop
                if kind == "batch" and owner["kind"] == "interactive":
                    db.execute("UPDATE gpu_leases SET kind='batch', route=?, project_id=? WHERE id=?", (route, project_id, owner["id"]))
                return Grant("granted", owner["id"])
            queue = [r["session_id"] for r in db.execute("SELECT session_id FROM gpu_leases WHERE state='queued' ORDER BY created, rowid")]
            reason = ""
            if self.maintenance_flag.exists():
                reason = "maintenance"
            elif owner:
                reason = "other session"
            elif external_busy or not device_lock_free(self.lock_dir, self.device):
                reason = "external"
            elif kind == "batch" and queue and queue[0] != session_id:
                reason = "queue"
            elif kind == "interactive" and queue:
                reason = "queue"  # waiting batch work goes first; clicks do not jump the queue
            if not reason and kind == "batch" and self._over_budget(db, session_id, now):
                return Grant("busy", reason="budget")
            if not reason:
                db.execute("DELETE FROM gpu_leases WHERE state='queued' AND session_id=?", (session_id,))
                lease_id = uuid.uuid4().hex
                db.execute("INSERT INTO gpu_leases(id, session_id, project_id, kind, route, state, created, started) "
                           "VALUES (?,?,?,?,?,'running',?,?)", (lease_id, session_id, project_id, kind, route, now, now))
                return Grant("granted", lease_id, new=True)
            if kind == "interactive":
                return Grant("busy", reason=reason)
            if session_id in queue:
                db.execute("UPDATE gpu_leases SET route=?, body=?, project_id=? WHERE session_id=? AND state='queued'",
                           (route, body, project_id, session_id))
                return Grant("queued", position=queue.index(session_id) + 1, reason=reason)
            if self._over_budget(db, session_id, now):
                return Grant("busy", reason="budget")
            db.execute("INSERT INTO gpu_leases(id, session_id, project_id, kind, route, body, state, created) "
                       "VALUES (?,?,?,?,?,?,'queued',?)", (uuid.uuid4().hex, session_id, project_id, kind, route, body, now))
            return Grant("queued", position=len(queue) + 1, reason=reason)

    def _over_budget(self, db, session_id: str, now: float) -> bool:
        rows = db.execute("SELECT started, ended FROM gpu_leases WHERE session_id=? AND kind='batch' AND started IS NOT NULL "
                          "AND (ended IS NULL OR ended > ?)", (session_id, now - 86400)).fetchall()
        return sum((r["ended"] or now) - max(r["started"], now - 86400) for r in rows) >= DAILY_BATCH_SECONDS

    def promote_next(self, now: float | None = None, external_busy: bool = False) -> dict | None:
        """Give the free GPU to the first queued batch request (the caller forwards it).

        external_busy: a CUDA process outside the web service (the desktop app, which does
        not take the shared lock) is on the GPU — queued work keeps waiting, like new work.
        """
        now = time.time() if now is None else now
        if external_busy or self.maintenance_flag.exists() or not device_lock_free(self.lock_dir, self.device):
            return None
        try:
            with self.db.connect(immediate=True) as db:
                if db.execute(f"SELECT 1 FROM gpu_leases WHERE state IN {HOLDING}").fetchone():
                    return None
                row = db.execute("SELECT * FROM gpu_leases WHERE state='queued' ORDER BY created, rowid LIMIT 1").fetchone()
                if not row:
                    return None
                db.execute("UPDATE gpu_leases SET state='running', started=? WHERE id=?", (now, row["id"]))
                return dict(row)
        except sqlite3.IntegrityError:
            return None

    def finish(self, lease_id: str, state: str, message: str = "", now: float | None = None):
        assert state in ("completed", "failed", "cancelled")
        with self.db.connect(immediate=True) as db:
            db.execute(f"UPDATE gpu_leases SET state=?, ended=?, message=? WHERE id=? AND state IN {HOLDING + ('queued',)}",
                       (state, time.time() if now is None else now, message[:300], lease_id))

    def release_if_idle(self, holder_running: bool) -> bool:
        """Release the holding lease once its work is really over (no running stage, lock free)."""
        owner = self.owner()
        if not owner or holder_running or not device_lock_free(self.lock_dir, self.device):
            return False
        self.finish(owner["id"], "completed", "GPU released (verified: no running stage, lock free)")
        return True

    def drop_session(self, session_id: str):
        with self.db.connect(immediate=True) as db:
            db.execute("UPDATE gpu_leases SET state='cancelled', ended=? WHERE session_id=? AND state='queued'",
                       (time.time(), session_id))
