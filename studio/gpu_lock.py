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
    base = Path(os.environ.get("XDG_RUNTIME_DIR", Path.home() / ".cache")) / "object-aware-studio-locks"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    return base / (hashlib.sha256(str(device).encode()).hexdigest() + ".lock")


def try_acquire(device):
    """Return an open locked file handle, or None if another process holds the GPU."""
    handle = lock_path(device).open("a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except BlockingIOError:
        handle.close()
        return None
