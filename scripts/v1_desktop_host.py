"""Isolated native QA host; operates only its own Qt window, never global input."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow
from studio.desktop.app import main

commands = Path(sys.argv[1])
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
app = QApplication(["m4ml-studio-v1-qa"])
previous = None


def tick():
    global previous
    if not commands.is_file():
        return
    raw = commands.read_text()
    if raw == previous:
        return
    try:
        request = json.loads(raw)
    except ValueError:
        return
    window = next(
        (w for w in app.topLevelWidgets() if isinstance(w, QMainWindow)), None
    )
    if window is None:
        return
    previous = raw
    if "size" in request:
        width, height = request["size"]
        window.showNormal()
        window.resize(max(1024, min(width, 2100)), max(640, min(height, 1400)))
    if request.get("close"):
        window.close()


timer = QTimer()
timer.timeout.connect(tick)
timer.start(100)
raise SystemExit(main(application=app))
