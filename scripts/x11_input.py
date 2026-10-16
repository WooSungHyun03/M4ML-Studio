"""Window-targeted X11 helper for desktop QA.

    python3 scripts/x11_input.py resize WINDOW_ID W H

Only operations addressed to one window ID are offered. Global pointer injection (XTest)
was removed on purpose: on a shared desktop it lands in whatever window is on top.
Mouse input for desktop QA goes to the M4ML page only, via QtWebEngine DevTools
``Input.dispatchMouseEvent`` (see scripts/desktop_live_render_qa.mjs).
"""

import ctypes
import sys

x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
x11.XOpenDisplay.restype = ctypes.c_void_p

if __name__ == "__main__":
    cmd, *a = sys.argv[1:]
    if cmd != "resize":
        raise SystemExit("only 'resize WINDOW_ID W H' is supported")
    dpy = ctypes.c_void_p(x11.XOpenDisplay(None))
    if not dpy:
        raise SystemExit("cannot open X display")
    x11.XResizeWindow(dpy, ctypes.c_ulong(int(a[0], 0)), int(a[1]), int(a[2]))
    x11.XFlush(dpy)
    x11.XCloseDisplay(dpy)
