"""Actual product QWebChannel/file dialogs/drop/download, scoped to an isolated Qt app.

Uses Qt's own widget/event APIs; no global desktop input or replacement dialogs.
Reuses a genuine existing colored mesh only for native export byte verification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ap = argparse.ArgumentParser()
ap.add_argument("--out", type=Path, required=True)
ap.add_argument("--photo", type=Path, required=True)
ap.add_argument("--mesh", type=Path, required=True)
args = ap.parse_args()
out, photo, mesh = args.out.resolve(), args.photo.resolve(), args.mesh.resolve()
out.mkdir(parents=True, exist_ok=False)
os.environ.update(STUDIO_DATA=str(out / "projects-data"), XDG_CONFIG_HOME=str(out / "config"),
                  XDG_DATA_HOME=str(out / "xdg-data"), XDG_CACHE_HOME=str(out / "cache"), STUDIO_PORT="8776",
                  QTWEBENGINE_REMOTE_DEBUGGING="127.0.0.1:9335")
from studio.store import Store
from studio.mesh import validate_mesh

store = Store()
image_project = store.create("파일 끌어놓기 시험")
mesh_project = store.create("실제 색상 메시 내보내기 시험")
dest = store.path(mesh_project["id"]) / "mesh"
dest.mkdir()
shutil.copyfile(mesh, dest / "fuse_post.ply")
info = validate_mesh(dest / "fuse_post.ply", dest)
store.update(mesh_project["id"], lambda d: d.update(input_mode="mesh", mesh={**info, "path": "mesh"},
             stages={**d["stages"], "mesh": "completed"}))
original = hashlib.sha256(photo.read_bytes()).hexdigest()
from PySide6.QtCore import QCoreApplication, QMimeData, QPoint, QPointF, QTimer, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow
from studio.desktop.app import main

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
app = QApplication(["m4ml-studio-io-test"])
state = {"step": "ready", "busy": False, "start": time.monotonic(), "checks": []}
report = {"scope": "real product Qt dialogs, file drop, original colored PLY download; no new reconstruction", "checks": state["checks"]}
window = None
mime = QMimeData()
mime.setUrls([QUrl.fromLocalFile(str(photo))])


def record(name):
    state["checks"].append({"name": name, "pass": True})


def js(expression, callback):
    state["busy"] = True
    def receive(value):
        state["busy"] = False
        try:
            callback(value)
        except Exception as exc:
            report.update(error=repr(exc), step=state["step"])
            timer.stop()
            window.close()
    window.view.page().runJavaScript(expression, receive)


def advance(step):
    state["step"] = step
    print("native I/O:", step, flush=True)


def tick():
    global window
    try:
        if time.monotonic() - state["start"] > 120:
            raise TimeoutError("native I/O step timed out: " + state["step"])
        if window is None:
            window = next((w for w in app.topLevelWidgets() if isinstance(w, QMainWindow)), None)
            if window is None: return
        dialog = app.activeModalWidget()
        if isinstance(dialog, QFileDialog):
            if state["step"] == "folder":
                advance("folder-result")
                dialog.setDirectory(str(photo.parent))
                QTimer.singleShot(600, dialog.accept)
            elif state["step"] == "file":
                dialog.setDirectory(str(photo.parent))
                dialog.selectFile(str(photo))
                advance("file-result")
                QTimer.singleShot(600, dialog.accept)
            elif state["step"] == "download":
                dialog.selectFile(str(out / "exported.ply"))
                advance("download-result")
                QTimer.singleShot(600, dialog.accept)
            return
        if state["busy"]: return
        step = state["step"]
        if step == "ready":
            def ready(value):
                if value:
                    advance("folder")
                    window.view.page().runJavaScript('window.m4mlReady.then(b => b.pickFolder("폴더 선택 시험", p => window.__qaFolder = p)); true')
            js('!!window.m4mlReady && !!document.querySelector(".menubar")', ready)
        elif step == "folder-result":
            def folder(value):
                if value:
                    assert value == str(photo.parent), value
                    record("actual folder dialog and QWebChannel return")
                    advance("file")
                    window.view.page().runJavaScript('window.m4mlReady.then(b => b.pickFile("파일 선택 시험", "사진 (*.jpg *.JPG *.png)", p => window.__qaFile = p)); true')
            js('window.__qaFolder || ""', folder)
        elif step == "file-result":
            def file(value):
                if value:
                    assert value == str(photo), value
                    record("actual file dialog and QWebChannel return")
                    advance("drop-ready")
                    window.view.page().runJavaScript(f'setTimeout(()=>location.assign(location.origin + "/?project={image_project["id"]}"),100); true')
            js('window.__qaFile || ""', file)
        elif step == "drop-ready":
            def drop_ready(value):
                if value:
                    x, y = json.loads(value)
                    state["position"] = (x, y)
                    event = QDragEnterEvent(QPoint(int(x), int(y)), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                    target = window.view.focusProxy() or window.view
                    print("native drop target:", target.metaObject().className(), target.acceptDrops(), flush=True)
                    QCoreApplication.sendEvent(target, event)
                    move = QDragMoveEvent(QPoint(int(x), int(y)), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                    QCoreApplication.sendEvent(target, move)
                    advance("drop")
            js('(() => {const e=document.querySelector(".dropzone"); if(!e)return "";const b=e.getBoundingClientRect();return JSON.stringify([b.x+b.width/2,b.y+b.height/2])})()', drop_ready)
        elif step == "drop":
            x, y = state["position"]
            event = QDropEvent(QPointF(x, y), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            QCoreApplication.sendEvent(window.view.focusProxy() or window.view, event)
            advance("drop-result")
        elif step == "drop-result":
            if store.get(image_project["id"])["images"]:
                record("native file drag/drop uploaded a real photo")
                advance("mesh-ready")
                window.view.page().runJavaScript(f'setTimeout(()=>location.assign(location.origin + "/?project={mesh_project["id"]}"),100); true')
        elif step == "mesh-ready":
            def mesh_ready(value):
                if value:
                    record("actual color mesh loaded before native export")
                    advance("download")
                    window.view.page().runJavaScript('[...document.querySelectorAll(".toolbar a")].find(a=>a.download.endsWith(".ply")).click(); true')
            js('Number(document.querySelector(".three-host")?.dataset.colorMeshes || 0) > 0', mesh_ready)
        elif step == "download-result":
            downloaded = out / "exported.ply"
            if downloaded.exists() and downloaded.stat().st_size == mesh.stat().st_size:
                assert hashlib.sha256(downloaded.read_bytes()).hexdigest() == hashlib.sha256(mesh.read_bytes()).hexdigest()
                assert hashlib.sha256(photo.read_bytes()).hexdigest() == original
                record("native save dialog exports byte-identical original PLY")
                record("source photo unchanged")
                report["pass"] = True
                timer.stop()
                window.close()
    except Exception as exc:
        report["error"] = repr(exc)
        report["step"] = state["step"]
        timer.stop()
        if isinstance(app.activeModalWidget(), QFileDialog): app.activeModalWidget().reject()
        if window: window.close()
        else: app.quit()


timer = QTimer()
timer.timeout.connect(tick)
timer.start(150)
try:
    code = main(application=app)
finally:
    report["seconds"] = round(time.monotonic() - state["start"], 2)
    (out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
raise SystemExit(0 if report.get("pass") and code == 0 else 1)
