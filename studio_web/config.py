"""Web gateway configuration (environment variables, validated once at start-up)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARD_MAX_ACTIVE_SESSIONS = 4  # never more GPU workspaces than this, whatever the configuration says


@dataclass(frozen=True)
class Config:
    home: Path  # gateway state: gateway.sqlite, sessions/
    frontend: Path  # built UI (frontend/dist)
    python: Path  # interpreter that runs session backends (research runtime)
    checkpoint: Path | None  # SAM 3.1 weights, read-only, chosen by the operator
    hosts: tuple[str, ...]  # accepted Host header names
    max_active_sessions: int
    session_days: int
    gpu_lock_dir: Path
    backend_start_timeout: float
    trust_cloudflare: bool  # take the client address from CF-Connecting-IP (only via the loopback tunnel)
    sandbox: str  # "bwrap": each session backend in its own bubblewrap sandbox; "none": plain process
    bwrap: str | None  # bubblewrap binary; the service uses a copy only it may run (AppArmor userns)
    turnstile_sitekey: str | None  # public site key; when set, new sessions need a Turnstile token
    turnstile_secret_file: Path | None  # systemd credential or 0600 file; never the environment
    turnstile_verify_url: str
    public_host: str | None  # hostname Turnstile must report (the tunnel's public name)
    contact: str | None  # operator contact shown in the privacy notice (public)

    @property
    def sessions_dir(self) -> Path:
        return self.home / "sessions"

    @property
    def database(self) -> Path:
        return self.home / "gateway.sqlite"


def _secret_file(env: dict[str, str]) -> Path | None:
    if env.get("STUDIO_WEB_TURNSTILE_SECRET_FILE"):
        return Path(env["STUDIO_WEB_TURNSTILE_SECRET_FILE"])
    if env.get("CREDENTIALS_DIRECTORY"):  # systemd LoadCredential=turnstile:...
        return Path(env["CREDENTIALS_DIRECTORY"]) / "turnstile"
    return None


def load(env: dict[str, str] | None = None) -> Config:
    env = dict(os.environ if env is None else env)
    home = env.get("STUDIO_WEB_HOME")
    if not home:
        raise RuntimeError("STUDIO_WEB_HOME(웹 서비스 데이터 폴더)를 지정하세요.")
    active = int(env.get("STUDIO_WEB_MAX_ACTIVE_SESSIONS", "3"))
    if not 1 <= active <= HARD_MAX_ACTIVE_SESSIONS:
        raise RuntimeError(f"STUDIO_WEB_MAX_ACTIVE_SESSIONS는 1~{HARD_MAX_ACTIVE_SESSIONS}이어야 합니다.")
    checkpoint = env.get("STUDIO_WEB_SAM_CHECKPOINT")
    lock_dir = env.get("STUDIO_GPU_LOCK_DIR")
    config = Config(
        home=Path(home).resolve(),
        frontend=Path(env.get("STUDIO_WEB_FRONTEND", ROOT / "frontend/dist")).resolve(),
        python=Path(env.get("STUDIO_WEB_PYTHON", ROOT / ".runtime/bin/python")),
        checkpoint=Path(checkpoint).resolve() if checkpoint else None,
        hosts=tuple(h.strip().lower() for h in env.get("STUDIO_WEB_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()),
        max_active_sessions=active,
        session_days=int(env.get("STUDIO_WEB_SESSION_DAYS", "7")),
        # Every session backend must use the same GPU lock (their XDG_RUNTIME_DIRs differ).
        gpu_lock_dir=Path(lock_dir) if lock_dir else Path(home).resolve() / "locks",
        backend_start_timeout=float(env.get("STUDIO_WEB_BACKEND_TIMEOUT", "60")),
        trust_cloudflare=env.get("STUDIO_WEB_TRUST_CLOUDFLARE") == "1",
        sandbox=env.get("STUDIO_WEB_SANDBOX", "none"),
        bwrap=env.get("STUDIO_WEB_BWRAP") or None,
        turnstile_sitekey=env.get("STUDIO_WEB_TURNSTILE_SITEKEY") or None,
        turnstile_secret_file=_secret_file(env),
        turnstile_verify_url=env.get("STUDIO_WEB_TURNSTILE_VERIFY_URL", "https://challenges.cloudflare.com/turnstile/v0/siteverify"),
        public_host=env.get("STUDIO_WEB_PUBLIC_HOST") or None,
        contact=env.get("STUDIO_WEB_CONTACT") or None,
    )
    if config.turnstile_sitekey and not (config.turnstile_secret_file and config.turnstile_secret_file.is_file()):
        raise RuntimeError("Turnstile 사이트 키가 있으면 비밀 키 파일도 있어야 합니다.")
    if config.contact and not re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", config.contact):
        raise RuntimeError("STUDIO_WEB_CONTACT는 이메일 주소여야 합니다.")
    if config.sandbox not in ("none", "bwrap"):
        raise RuntimeError("STUDIO_WEB_SANDBOX는 none 또는 bwrap이어야 합니다.")
    if config.home in (Path.home().resolve(), Path("/")):
        raise RuntimeError("웹 서비스 데이터 폴더로 홈이나 루트를 쓸 수 없습니다.")
    return config
