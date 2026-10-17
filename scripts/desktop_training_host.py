"""Isolated Qt QA host: acknowledge ONLY the real 100-iteration training dialog.

QtWebEngine's modal dialog may block its DevTools mouse acknowledgement. A QTimer
operates the actual button in this test QApplication; no global input or fake dialog.
Use STUDIO_DATA / STUDIO_PORT / QTWEBENGINE_REMOTE_DEBUGGING for isolated test data.
"""

import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QPushButton,
    QLabel,
    QDialogButtonBox,
)
from studio.desktop.app import main

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
app = QApplication(["m4ml-studio-training-qa"])
accepted = set()


def inspect_dialog():
    dialog = app.activeModalWidget()
    if not isinstance(dialog, QDialog) or id(dialog) in accepted:
        return
    text = " ".join(l.text() for l in dialog.findChildren(QLabel))
    if "100회" not in text or "3D 재구성" not in text:
        return
    box = dialog.findChild(QDialogButtonBox)
    if box:
        button = box.button(QDialogButtonBox.Ok) or box.button(QDialogButtonBox.Yes)
    else:
        button = next(
            (
                b
                for b in dialog.findChildren(QPushButton)
                if b.text().replace("&", "").lower() in ("ok", "yes", "확인", "예")
            ),
            None,
        )
    if button:
        accepted.add(id(dialog))
        print(
            json.dumps({"actual_100_iteration_dialog": text, "button": button.text()}),
            flush=True,
        )
        button.click()


timer = QTimer()
timer.timeout.connect(inspect_dialog)
timer.start(100)
raise SystemExit(main(application=app))
