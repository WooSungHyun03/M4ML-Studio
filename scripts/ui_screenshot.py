#!/usr/bin/env python3
"""Capture real screenshots of the running app (headless Chrome, no mocks).

  python3 scripts/ui_screenshot.py URL OUT.png [WIDTH HEIGHT] [--wait-ms N]
Used for visual regression checks of the live UI against the design package.
"""
import glob, os, shutil, subprocess, sys, tempfile

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    wait = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--wait-ms=")), 8000)
    url, out = args[0], args[1]
    w, h = (int(args[2]), int(args[3])) if len(args) > 3 else (1920, 1080)
    shells = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell")))
    chrome = os.environ.get("CHROME") or (shells[-1] if shells else shutil.which("google-chrome"))
    prof = tempfile.mkdtemp(prefix="m4ml-ui-")
    try:
        subprocess.run([chrome, f"--user-data-dir={prof}", "--hide-scrollbars", "--use-angle=swiftshader",
                        "--enable-unsafe-swiftshader", f"--window-size={w},{h}", f"--virtual-time-budget={wait}",
                        "--run-all-compositor-stages-before-draw", f"--screenshot={os.path.abspath(out)}", url],
                       capture_output=True, timeout=180, check=True)
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    print(out)

if __name__ == "__main__":
    main()
