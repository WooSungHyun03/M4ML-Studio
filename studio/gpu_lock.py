"""One OS-level exclusive lock per physical GPU, shared by workers and live sessions.

Heavy GPU users (camera reconstruction on GPU, mask propagation, reconstruction training,
3D model generation, and the interactive object-selection session) take this lock so
they never compete for VRAM. The lock is an fcntl lock: it disappears automatically if
the owning process dies, so a crash can never leave the GPU "reserved".
"""

import fcntl
import hashlib
import os
from pathlib import Path


def lock_path(device):
    # The default directory is per Linux user. STUDIO_GPU_LOCK_DIR names a directory shared
    # by several accounts (the web service and the desktop user) so they exclude each other.
    shared = os.environ.get("STUDIO_GPU_LOCK_DIR")
    if shared:
        base = Path(shared)
        if not base.is_dir():
            raise RuntimeError(f"공용 GPU 잠금 폴더가 없습니다: {base}")
        return base / (hashlib.sha256(str(device).encode()).hexdigest() + ".lock")
    base = Path(os.environ.get("XDG_RUNTIME_DIR", Path.home() / ".cache")) / "object-aware-studio-locks"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    return base / (hashlib.sha256(str(device).encode()).hexdigest() + ".lock")


def try_acquire(device):
    """Return an open locked file handle, or None if another process holds the GPU."""
    path = lock_path(device)
    try:
        handle = path.open("a")
    except PermissionError:
        # Shared directory: a lock file created by another account may not be writable
        # for us. flock() works on a read-only descriptor as well.
        handle = path.open("r")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except BlockingIOError:
        handle.close()
        return None
