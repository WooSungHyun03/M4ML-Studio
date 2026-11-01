"""Deleting workspaces: on request, at expiry (7 days), and again after a crash.

A session is marked 'deleting' first (its cookie stops working at once), then its backend
and every process below it are stopped, its slot, queue place and recovery link are
dropped, its folder is moved aside atomically and removed, and only then is it marked
'deleted'. Each step is safe to repeat, so a sweep after a restart finishes what a crash
interrupted. The session row stays (state 'deleted', no secrets) so its id is never reused.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from studio_web.persistence.db import Database


def mark_deleting(db: Database, session_id: str) -> None:
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE sessions SET state='deleting' WHERE id=? AND state='active'", (session_id,))


def finish(db: Database, backends, slots, session_id: str) -> bool:
    """Complete the deletion of a session marked 'deleting'. Returns True when nothing is left."""
    backends.stop(session_id)
    slots.release(session_id)
    with db.connect(immediate=True) as conn:
        conn.execute("DELETE FROM recovery WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM backends WHERE session_id=?", (session_id,))
    folder = Path(backends.session_dir(session_id))
    doomed = folder.with_name(".deleting-" + session_id)
    if folder.exists():
        os.replace(folder, doomed)
    if doomed.exists():
        shutil.rmtree(doomed, ignore_errors=True)
    if folder.exists() or doomed.exists():
        db.audit(session_id, "session deletion incomplete; will retry")
        return False
    with db.connect(immediate=True) as conn:
        # forget the credential hashes too: nothing can match this session again
        conn.execute("UPDATE sessions SET state='deleted', token_hash='deleted:'||id, csrf='' WHERE id=?", (session_id,))
    db.audit(session_id, "session deleted")
    return True


def delete_session(db: Database, backends, slots, session_id: str) -> bool:
    mark_deleting(db, session_id)
    return finish(db, backends, slots, session_id)


RECORD_DAYS = 30  # audit events, GPU lease history, deleted-session rows (see the privacy notice)


def prune_records(db: Database, now: float | None = None) -> dict:
    """Operational records older than RECORD_DAYS are removed (no photos are ever in them)."""
    cutoff = (time.time() if now is None else now) - RECORD_DAYS * 86400
    with db.connect(immediate=True) as conn:
        counts = {
            "audit": conn.execute("DELETE FROM audit WHERE at < ?", (cutoff,)).rowcount,
            "gpu_leases": conn.execute("DELETE FROM gpu_leases WHERE state IN ('completed','failed','cancelled') "
                                       "AND COALESCE(ended, created) < ?", (cutoff,)).rowcount,
            "issuance": conn.execute("DELETE FROM issuance WHERE at < ?", (cutoff,)).rowcount,
        }
        gone = [r[0] for r in conn.execute("SELECT id FROM sessions WHERE state='deleted' AND last_seen < ?", (cutoff,))]
        for sid in gone:
            if not conn.execute("SELECT 1 FROM gpu_leases WHERE session_id=?", (sid,)).fetchone():
                conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
        counts["sessions"] = len(gone)
    return counts


def sweep(db: Database, backends, slots, now: float | None = None) -> list[str]:
    """Expire sessions past their lifetime, finish interrupted deletions, prune old records."""
    now = time.time() if now is None else now
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE sessions SET state='deleting' WHERE state='active' AND expires < ?", (now,))
        due = [r[0] for r in conn.execute("SELECT id FROM sessions WHERE state='deleting'")]
    done = [sid for sid in due if finish(db, backends, slots, sid)]
    prune_records(db, now)
    return done
