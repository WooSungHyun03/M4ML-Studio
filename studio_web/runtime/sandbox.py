"""Per-session process sandbox (bubblewrap) for web session backends.

A session backend sees only: the read-only system (/usr, /etc, /sys), the read-only
application and runtime, its own session folder (read-write, at /session), NVIDIA device
nodes, and private /tmp, /home, /run. Optionally no network namespace access at all.

This is a mount-namespace boundary on top of the account boundary, not a replacement for
it: processes inside still run with the service account's UID. On Ubuntu 24.04 an
unprivileged user namespace needs an AppArmor profile that allows `userns` for bwrap when
started from a system service (see web-harness/state/ISOLATION_BASELINE.md).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

SESSION_MOUNT = "/session"


@dataclass(frozen=True)
class SandboxSpec:
    session_dir: Path  # read-write, mounted at /session
    read_only: tuple[Path, ...]  # application code, runtime, model weights
    read_write: tuple[Path, ...] = ()  # shared state every session needs (the GPU lock directory)
    network: bool = False  # False: own network namespace with loopback only
    gpu: bool = True
    env: dict[str, str] = field(default_factory=dict)
    chdir: Path | None = None  # working directory inside the sandbox (must be a bound path)
    # PR_SET_PDEATHSIG follows the *thread* that started bwrap. Session backends are started
    # from a thread pool and must outlive it (and the gateway), so they turn this off.
    die_with_parent: bool = True


def environment(spec: SandboxSpec) -> dict[str, str]:
    """The complete environment to start bwrap with (and so the sandbox's environment)."""
    return {"PATH": "/usr/bin:/bin", "HOME": f"{SESSION_MOUNT}/home", "LANG": "C.UTF-8", **spec.env}


def bwrap_argv(spec: SandboxSpec, command: list[str], bwrap: str | None = None) -> list[str]:
    binary = bwrap or shutil.which("bwrap")
    if not binary:
        raise RuntimeError("bubblewrap(bwrap)가 설치되어 있지 않습니다.")
    session = Path(spec.session_dir).resolve()
    if not session.is_dir():
        raise ValueError("세션 폴더가 없습니다.")
    argv = [
        binary, *(["--die-with-parent"] if spec.die_with_parent else []), "--new-session",
        "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--unshare-cgroup-try",
        "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc",
        "--ro-bind", "/sys", "/sys",  # NVML enumerates the PCI tree under /sys
        "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
        "--symlink", "usr/bin", "/bin", "--symlink", "usr/sbin", "/sbin",
        "--proc", "/proc", "--dev", "/dev",
        "--tmpfs", "/tmp", "--tmpfs", "/home", "--tmpfs", "/run",
    ]
    for path in spec.read_only:
        resolved = Path(path).resolve()
        if not resolved.exists():
            raise ValueError(f"읽기 전용으로 연결할 경로가 없습니다: {resolved}")
        if resolved == session or resolved in session.parents or session in resolved.parents:
            raise ValueError("세션 폴더와 읽기 전용 경로가 겹칩니다.")
        argv += ["--ro-bind", str(resolved), str(resolved)]
    for path in spec.read_write:
        resolved = Path(path).resolve()
        if not resolved.is_dir():
            raise ValueError(f"쓰기 가능으로 연결할 폴더가 없습니다: {resolved}")
        argv += ["--bind", str(resolved), str(resolved)]
    argv += ["--bind", str(session), SESSION_MOUNT]
    if spec.gpu:
        for node in sorted(Path("/dev").glob("nvidia*")):
            argv += ["--dev-bind", str(node), str(node)]
    if not spec.network:
        argv.append("--unshare-net")
    # Environment values (the backend token among them) never go on the command line, which
    # every local account can read in /proc: bwrap hands its own environment to the sandbox,
    # and the caller starts bwrap with exactly `environment(spec)`.
    if spec.chdir:
        argv += ["--chdir", str(spec.chdir)]
    return argv + ["--", *command]
