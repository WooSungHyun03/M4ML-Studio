"""Anonymous sessions: the cookie secret is the credential; only its hash is stored."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from studio_web.persistence.db import Database

SESSION_COOKIE = "__Host-m4ml_session"  # HttpOnly
LAST_SEEN_EVERY = 60  # seconds between activity-time writes for one session
CSRF_COOKIE = "__Host-m4ml_csrf"  # readable by the page (double submit)


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


@dataclass(frozen=True)
class Session:
    id: str
    csrf: str
    expires: float


class Sessions:
    def __init__(self, db: Database, days: int):
        self.db, self.ttl = db, days * 86400

    def create(self) -> tuple[Session, str]:
        """Return the session and the cookie secret (shown to the browser once, never stored)."""
        secret, internal, csrf = secrets.token_urlsafe(32), secrets.token_hex(16), secrets.token_urlsafe(24)
        now = time.time()
        with self.db.connect() as db:
            db.execute(
                "INSERT INTO sessions(id, token_hash, csrf, created, last_seen, expires, state) VALUES (?,?,?,?,?,?, 'active')",
                (internal, digest(secret), csrf, now, now, now + self.ttl),
            )
        self.db.audit(internal, "session created")
        return Session(internal, csrf, now + self.ttl), secret

    def lookup(self, secret: str | None) -> Session | None:
        if not secret or len(secret) > 128:
            return None
        now = time.time()
        with self.db.connect() as db:
            row = db.execute("SELECT id, csrf, expires, state, last_seen FROM sessions WHERE token_hash=?", (digest(secret),)).fetchone()
            if not row or row["state"] != "active" or row["expires"] < now:
                return None
            if now - row["last_seen"] > LAST_SEEN_EVERY:  # a disk write per request would cost ~50 ms here
                db.execute("UPDATE sessions SET last_seen=? WHERE id=?", (now, row["id"]))
        return Session(row["id"], row["csrf"], row["expires"])

    @staticmethod
    def csrf_ok(session: Session, header: str | None, cookie: str | None) -> bool:
        if not header or not cookie:
            return False
        return hmac.compare_digest(header, cookie) and hmac.compare_digest(header, session.csrf)


ISSUE_PER_HOUR = 5  # new anonymous sessions per client address per hour (Turnstile comes on top, T21)


class Recovery:
    """One-time links that move a workspace to another browser.

    The link carries its own secret (never the session cookie). Using it rotates the
    session's cookie secret and CSRF token, so the browser that held the old cookie is
    signed out of that workspace ("takeover"); the link itself is consumed.
    """

    def __init__(self, db: Database):
        self.db = db

    def issue(self, session: Session) -> str:
        token = secrets.token_urlsafe(32)
        with self.db.connect(immediate=True) as db:
            db.execute("DELETE FROM recovery WHERE session_id=?", (session.id,))
            db.execute("INSERT INTO recovery(session_id, token_hash, created, expires) VALUES (?,?,?,?)",
                       (session.id, digest(token), time.time(), session.expires))
        self.db.audit(session.id, "recovery link issued")
        return token

    def redeem(self, token: str | None) -> tuple[Session, str] | None:
        if not token or len(token) > 128:
            return None
        now = time.time()
        with self.db.connect(immediate=True) as db:
            row = db.execute(
                "SELECT r.session_id, r.expires, s.state, s.expires AS s_expires FROM recovery r JOIN sessions s ON s.id=r.session_id "
                "WHERE r.token_hash=?", (digest(token),)).fetchone()
            if not row:
                return None
            db.execute("DELETE FROM recovery WHERE session_id=?", (row["session_id"],))  # one use only
            if row["state"] != "active" or row["expires"] < now or row["s_expires"] < now:
                return None
            secret, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
            db.execute("UPDATE sessions SET token_hash=?, csrf=?, last_seen=? WHERE id=?",
                       (digest(secret), csrf, now, row["session_id"]))
        self.db.audit(row["session_id"], "recovery link used; cookie rotated")
        return Session(row["session_id"], csrf, row["s_expires"]), secret


def issuance_allowed(db: Database, client: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    with db.connect(immediate=True) as conn:
        conn.execute("DELETE FROM issuance WHERE at < ?", (now - 3600,))
        if conn.execute("SELECT COUNT(*) FROM issuance WHERE client=?", (client,)).fetchone()[0] >= ISSUE_PER_HOUR:
            return False
        conn.execute("INSERT INTO issuance(client, at) VALUES (?,?)", (client, now))
    return True
