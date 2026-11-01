"""Cloudflare Turnstile server-side verification (Siteverify) for new anonymous sessions.

The widget's token is only a claim; the gateway asks Cloudflare and accepts it when the
answer says success for *our* hostname and action. Tokens are single-use: a token seen
before is refused here too, without asking Cloudflare again. Any doubt (timeout, bad
answer) refuses the session — nothing is opened on a failed check.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid

import httpx

ACTION = "session"
TOKEN_MAX = 2048
_seen: dict[str, float] = {}  # sha256(token) -> time; tokens are valid 300 s at most


class Verdict:
    def __init__(self, ok: bool, reason: str = ""):
        self.ok, self.reason = ok, reason


async def verify(token: str | None, *, secret: str, url: str, remote_ip: str | None, expected_host: str | None) -> Verdict:
    if not token or len(token) > TOKEN_MAX:
        return Verdict(False, "missing")
    now = time.time()
    for key, at in list(_seen.items()):
        if now - at > 300:
            del _seen[key]
    digest = hashlib.sha256(token.encode()).hexdigest()
    if digest in _seen:
        return Verdict(False, "replay")
    _seen[digest] = now
    form = {"secret": secret, "response": token, "idempotency_key": str(uuid.uuid4())}
    if remote_ip:
        form["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            reply = (await client.post(url, data=form)).json()
    except (httpx.HTTPError, ValueError):
        return Verdict(False, "unreachable")
    if not isinstance(reply, dict) or reply.get("success") is not True:
        # Cloudflare's error codes (e.g. invalid-input-secret) tell the operator what is wrong;
        # only that fixed vocabulary is kept, never the token or the secret.
        codes = reply.get("error-codes") if isinstance(reply, dict) else None
        names = [c for c in codes if isinstance(c, str) and re.fullmatch(r"[a-z-]{1,40}", c)][:3] if isinstance(codes, list) else []
        return Verdict(False, "rejected" + (":" + ",".join(names) if names else ""))
    if expected_host and reply.get("hostname") != expected_host:
        return Verdict(False, "hostname")
    if reply.get("action") not in (None, "", ACTION):
        return Verdict(False, "action")
    return Verdict(True)
