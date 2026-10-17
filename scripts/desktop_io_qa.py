"""Actual product QWebChannel/file dialogs/drop/download, scoped to an isolated Qt app.

Uses Qt's own widget/event APIs; no global desktop input or replacement dialogs.
Reuses a genuine existing colored mesh only for native export byte verification.
Export cases: PLY and GLB byte identity at the exact chosen path, cancel (nothing written),
overwrite of an existing file after Qt's confirmation (same path, no "(1)" copy), and an
unwritable folder (product warns, dialog reopens, no partial file). Runs with
QT_QPA_PLATFORM=offscreen so no window appears on a shared desktop.
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
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QLineEdit, QMessageBox, QPushButton
from PySide6.QtTest import QTest
from studio.desktop.app import main

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
app = QApplication(["m4ml-studio-io-test"])
state = {"step": "ready", "busy": False, "start": time.monotonic(), "checks": []}
report = {"scope": "real product Qt dialogs, file drop, original colored PLY download; no new reconstruction", "checks": state["checks"]}
window = None
EXPORTS = [  # (name, link suffix, dialog answers, expected file, expected source)
    {"name": "PLY", "ext": ".ply", "paths": ["exported.ply"]},
    {"name": "GLB", "ext": ".glb", "paths": ["exported.glb"]},
    {"name": "cancel", "ext": ".ply", "paths": [None]},
    {"name": "overwrite", "ext": ".ply", "paths": ["exists.ply"]},
    {"name": "unwritable", "ext": ".ply", "paths": ["readonly/blocked.ply", "after-invalid.ply"]},
]
(out / "exists.ply").write_bytes(b"old file that the user agreed to replace\n")
(out / "readonly").mkdir()
os.chmod(out / "readonly", 0o555)
state["export"] = 0
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


def select_dialog_path(dialog, path, proof):
    dialog.selectFile(str(path))
    fields = dialog.findChildren(QLineEdit)
    print("native dialog fields:", [(e.objectName(), e.text(), e.isVisible()) for e in fields], flush=True)
    if dialog.selectedFiles() != [str(path)]:
        filename = next((e for e in fields if e.objectName() == "fileNameEdit"), None)
        if filename is not None:
            filename.setFocus()
            QTest.keyClick(filename, Qt.Key_A, Qt.ControlModifier)
            QTest.keyClicks(filename, str(path))
    print("native selected paths:", dialog.selectedFiles(), "mode", str(dialog.fileMode()), flush=True)
    state.setdefault("dialog_buttons", []).extend(b.text() for b in dialog.findChildren(QPushButton) if b.isVisible())
    dialog.grab().save(str(out / proof))
    dialog.accept()


def tick():
    global window
    try:
        if time.monotonic() - state["start"] > 240:
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
                advance("file-result")
                def select_photo():
                    # QFileSystemModel may reset selection when directory loading
                    # completes. Select after that load, as a person would.
                    select_dialog_path(dialog, photo, "actual-file-dialog.png")
                QTimer.singleShot(600, select_photo)
            elif state["step"] in ("download", "download-result"):
                case = EXPORTS[state["export"]]
                answers = case.setdefault("pending", list(case["paths"]))
                if state.get("dialog_id") == id(dialog):
                    return
                state["dialog_id"] = id(dialog)
                state["dialogs"] = state.get("dialogs", 0) + 1
                advance("download-result")
                answer = answers.pop(0) if answers else None
                def respond():
                    if answer is None:
                        dialog.grab().save(str(out / "actual-save-dialog-cancel.png"))
                        dialog.reject()
                    else:
                        select_dialog_path(dialog, out / answer, f"actual-save-dialog-{case['name']}.png")
                QTimer.singleShot(600, respond)
            return
        if isinstance(dialog, QMessageBox):
            # Qt's own overwrite confirmation or the product's unwritable-folder warning.
            if state.get("box_id") == id(dialog):
                return
            state["box_id"] = id(dialog)
            text = dialog.text()
            print("native message box:", text.replace("\n", " / "), flush=True)
            state.setdefault("messages", []).append(text)
            dialog.grab().save(str(out / f"actual-message-{len(state['messages'])}.png"))
            yes = dialog.button(QMessageBox.Yes)
            QTimer.singleShot(300, (yes.click if yes else dialog.accept))
            state["dialog_id"] = None
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
                    start_export()
            js('Number(document.querySelector(".three-host")?.dataset.colorMeshes || 0) > 0', mesh_ready)
        elif step == "download-result":
            check_export()
    except Exception as exc:
        report["error"] = repr(exc)
        report["step"] = state["step"]
        timer.stop()
        if isinstance(app.activeModalWidget(), QFileDialog): app.activeModalWidget().reject()
        if window: window.close()
        else: app.quit()


def source_for(ext):
    return mesh if ext == ".ply" else dest / "preview.glb"


def start_export():
    case = EXPORTS[state["export"]]
    state["export_started"] = time.monotonic()
    state["before"] = sorted(p.name for p in out.iterdir())
    advance("download")
    window.view.page().runJavaScript(
        f'[...document.querySelectorAll(".toolbar a")].find(a=>a.download.endsWith("{case["ext"]}")).click(); true')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_export():
    case = EXPORTS[state["export"]]
    src = source_for(case["ext"])
    parts = [p.name for p in out.rglob("*.part")]
    done = False
    if case["name"] == "cancel":
        if time.monotonic() - state["export_started"] > 4 and state.get("dialog_id"):
            after = sorted(p.name for p in out.iterdir() if not p.name.startswith("actual-"))
            before = [n for n in state["before"] if not n.startswith("actual-")]
            assert after == before and not parts, (before, after, parts)
            record("cancelled save dialog writes nothing")
            done = True
    else:
        target = out / case["paths"][-1]
        if target.exists() and target.stat().st_size == src.stat().st_size and not parts:
            assert sha(target) == sha(src), case
            if case["name"] == "PLY":
                record("native save dialog exports byte-identical original PLY at the chosen path")
            elif case["name"] == "GLB":
                assert target.read_bytes()[:4] == b"glTF"
                record("native save dialog exports byte-identical GLB (glTF) at the chosen path")
            elif case["name"] == "overwrite":
                assert any("이미" in m for m in state.get("messages", [])), state.get("messages")  # Korean Qt translation
                assert not list(out.glob("exists (*")) and not list(out.glob("exists*1*")), list(out.iterdir())
                record("existing file replaced at the same path only after Qt's overwrite confirmation")
            elif case["name"] == "unwritable":
                assert any("저장할 수 없습니다" in m for m in state.get("messages", [])), state.get("messages")
                assert not any((out / "readonly").iterdir())
                record("unwritable folder warns, reopens the dialog, then saves to the new path")
            done = True
    if done:
        state["export"] += 1
        state["dialog_id"] = None
        if state["export"] < len(EXPORTS):
            start_export()
        else:
            assert hashlib.sha256(photo.read_bytes()).hexdigest() == original
            assert sha(mesh) == sha(dest / "fuse_post.ply")
            record("source photo and project mesh unchanged")
            report["pass"] = True
            report["messages"] = state.get("messages", [])
            report["dialog_buttons"] = sorted(set(state.get("dialog_buttons", [])))
            assert not {"Save", "Open", "Cancel", "Choose"} & set(report["dialog_buttons"]), report["dialog_buttons"]
            record("Qt dialogs shown in Korean")
            timer.stop()
            window.close()


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
