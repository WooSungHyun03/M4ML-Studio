"""Gateway database: SQLite WAL with numbered migrations. Separate from every session store."""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS = [
    # 1: anonymous sessions and their backends
    """
    CREATE TABLE sessions(
      id TEXT PRIMARY KEY,               -- internal id, names the session folder; never sent to browsers
      token_hash TEXT NOT NULL UNIQUE,   -- sha256 of the cookie secret
      csrf TEXT NOT NULL,
      created REAL NOT NULL,
      last_seen REAL NOT NULL,
      expires REAL NOT NULL,
      state TEXT NOT NULL CHECK(state IN ('active','deleting','deleted'))
    );
    CREATE TABLE backends(
      session_id TEXT PRIMARY KEY REFERENCES sessions(id),
      port INTEGER NOT NULL,
      token TEXT NOT NULL,
      pid INTEGER NOT NULL,
      pid_start TEXT NOT NULL,
      started REAL NOT NULL
    );
    CREATE TABLE audit(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      at REAL NOT NULL,
      session_id TEXT,
      event TEXT NOT NULL
    );
    """,
    # 2: active workspace slots, the small waiting queue, recovery links, issuance limits
    """
    CREATE TABLE slots(
      session_id TEXT PRIMARY KEY REFERENCES sessions(id),
      acquired REAL NOT NULL,
      heartbeat REAL NOT NULL
    );
    CREATE TABLE queue(
      session_id TEXT PRIMARY KEY REFERENCES sessions(id),
      enqueued REAL NOT NULL,
      heartbeat REAL NOT NULL
    );
    CREATE TABLE recovery(
      session_id TEXT PRIMARY KEY REFERENCES sessions(id),
      token_hash TEXT NOT NULL UNIQUE,
      created REAL NOT NULL,
      expires REAL NOT NULL
    );
    CREATE TABLE issuance(
      client TEXT NOT NULL,
      at REAL NOT NULL
    );
    CREATE INDEX issuance_client ON issuance(client, at);
    """,
    # 3: backends listen on a UNIX socket inside their session folder (no TCP port)
    """
    ALTER TABLE backends ADD COLUMN socket TEXT;
    """,
    # 4: GPU leases. At most one lease may hold the GPU (allocating/running/releasing):
    # enforced by a unique index on a constant over exactly those states.
    """
    CREATE TABLE gpu_leases(
      id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL REFERENCES sessions(id),
      project_id TEXT NOT NULL,
      kind TEXT NOT NULL CHECK(kind IN ('batch','interactive')),
      route TEXT NOT NULL,
      body BLOB,
      state TEXT NOT NULL CHECK(state IN ('queued','allocating','running','releasing',
                                          'completed','failed','cancelled','uncertain')),
      created REAL NOT NULL,
      started REAL,
      ended REAL,
      message TEXT NOT NULL DEFAULT ''
    );
    CREATE UNIQUE INDEX one_gpu_owner ON gpu_leases((1)) WHERE state IN ('allocating','running','releasing');
    CREATE UNIQUE INDEX one_queued_batch ON gpu_leases(session_id) WHERE state='queued';
    CREATE INDEX lease_order ON gpu_leases(state, created);
    """,
]


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL)")
            row = db.execute("SELECT version FROM schema_version").fetchone()
            version = row[0] if row else 0
            if not row:
                db.execute("INSERT INTO schema_version(version) VALUES (0)")
            if version > len(MIGRATIONS):
                raise RuntimeError("웹 서비스 데이터베이스가 이 버전보다 새 버전입니다.")
            for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
                db.executescript("BEGIN;" + script + f"UPDATE schema_version SET version={number}; COMMIT;")
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self, immediate: bool = False):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        # WAL + NORMAL: commits do not fsync; after a power cut the last transactions may be
        # lost but the database stays consistent (sessions, slots and leases are re-checked).
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if immediate:
                db.execute("BEGIN IMMEDIATE")
                try:
                    yield db
                    db.execute("COMMIT")
                except BaseException:
                    db.execute("ROLLBACK")
                    raise
            else:
                yield db
        finally:
            db.close()

    def audit(self, session_id: str | None, event: str):
        with self.connect() as db:
            db.execute("INSERT INTO audit(at, session_id, event) VALUES (?,?,?)", (time.time(), session_id, event))

    def version(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT version FROM schema_version").fetchone()[0]
