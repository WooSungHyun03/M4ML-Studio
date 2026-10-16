"""Linux parent-death signal before exec; avoids orphaned CUDA processes."""

import ctypes
import os
import signal
import sys


if __name__ == "__main__":
    expected_parent = int(sys.argv[1])
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_PDEATHSIG")
    if os.getppid() != expected_parent:
        raise SystemExit(125)
    os.execvpe(sys.argv[2], sys.argv[2:], os.environ)
