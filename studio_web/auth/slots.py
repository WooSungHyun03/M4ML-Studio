"""Active workspace slots (default 3, never more than 4) and a small FIFO waiting queue.

A slot is what lets a session have a running backend. Slots are granted inside one
`BEGIN IMMEDIATE` transaction, so two browsers can never both take the last slot. Waiting
sessions are admitted strictly in arrival order; queue entries that stop polling expire.
Releasing a slot is the caller's job after its backend has no running work (see app.py).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from studio_web.config import HARD_MAX_ACTIVE_SESSIONS
from studio_web.persistence.db import Database

QUEUE_MAX = 2
QUEUE_STALE_SECONDS = 60  # a waiting page polls every few seconds
IDLE_SECONDS = 15 * 60  # an active slot with no request for this long may be reclaimed
HEARTBEAT_EVERY = 30  # seconds between heartbeat writes of an active slot


@dataclass(frozen=True)
class Admission:
    active: bool
    position: int | None = None  # 1-based place in the queue
    full: bool = False  # queue full too: come back later


class Slots:
    def __init__(self, db: Database, max_active: int):
        if not 1 <= max_active <= HARD_MAX_ACTIVE_SESSIONS:
            raise ValueError("max_active")
        self.db, self.max_active = db, max_active

    def admit(self, session_id: str, now: float | None = None) -> Admission:
        now = time.time() if now is None else now
        # Fast path, no write: a session that already holds a slot with a fresh heartbeat.
        with self.db.connect() as db:
            row = db.execute("SELECT heartbeat FROM slots WHERE session_id=?", (session_id,)).fetchone()
        if row and now - row["heartbeat"] < HEARTBEAT_EVERY:
            return Admission(True)
        with self.db.connect(immediate=True) as db:
            db.execute("DELETE FROM queue WHERE heartbeat < ?", (now - QUEUE_STALE_SECONDS,))
            if db.execute("SELECT 1 FROM slots WHERE session_id=?", (session_id,)).fetchone():
                db.execute("UPDATE slots SET heartbeat=? WHERE session_id=?", (now, session_id))
                return Admission(True)
            used = db.execute("SELECT COUNT(*) FROM slots").fetchone()[0]
            waiting = [r[0] for r in db.execute("SELECT session_id FROM queue ORDER BY enqueued, rowid")]
            first_in_line = not waiting or waiting[0] == session_id
            if used < min(self.max_active, HARD_MAX_ACTIVE_SESSIONS) and first_in_line:
                db.execute("DELETE FROM queue WHERE session_id=?", (session_id,))
                db.execute("INSERT INTO slots(session_id, acquired, heartbeat) VALUES (?,?,?)", (session_id, now, now))
                return Admission(True)
            if session_id in waiting:
                db.execute("UPDATE queue SET heartbeat=? WHERE session_id=?", (now, session_id))
                return Admission(False, waiting.index(session_id) + 1)
            if len(waiting) >= QUEUE_MAX:
                return Admission(False, full=True)
            db.execute("INSERT INTO queue(session_id, enqueued, heartbeat) VALUES (?,?,?)", (session_id, now, now))
            return Admission(False, len(waiting) + 1)

    def holds(self, session_id: str) -> bool:
        with self.db.connect() as db:
            return bool(db.execute("SELECT 1 FROM slots WHERE session_id=?", (session_id,)).fetchone())

    def touch(self, session_id: str, now: float | None = None):
        with self.db.connect() as db:
            db.execute("UPDATE slots SET heartbeat=? WHERE session_id=?", (time.time() if now is None else now, session_id))

    def idle(self, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        with self.db.connect() as db:
            return [r[0] for r in db.execute("SELECT session_id FROM slots WHERE heartbeat < ?", (now - IDLE_SECONDS,))]

    def release(self, session_id: str):
        with self.db.connect(immediate=True) as db:
            db.execute("DELETE FROM slots WHERE session_id=?", (session_id,))
            db.execute("DELETE FROM queue WHERE session_id=?", (session_id,))

    def active_count(self) -> int:
        with self.db.connect() as db:
            return db.execute("SELECT COUNT(*) FROM slots").fetchone()[0]
