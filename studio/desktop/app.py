"""M4ML Studio desktop application (PySide6 + QtWebEngine).

A native window hosts the existing React UI; no external browser is opened.
* starts the FastAPI backend as a child process on a free loopback port with a
  per-launch secret token (passed by environment, injected only into this window);
* exposes a small native bridge (QWebChannel object ``m4ml``): folder/file dialogs,
  open folder in file manager, full screen, quit, window title;
* saves downloads (PLY/GLB/screenshots) through a native save dialog;
* remembers window geometry; single instance; asks before quitting while a job runs;
* stops the backend gracefully (SIGTERM → wait → SIGKILL) and logs to
  ``$XDG_CACHE_HOME/m4ml-studio/desktop.log``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "m4ml-studio"
DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "m4ml-studio"
ICON = ROOT / "frontend/public/m4ml-icon.png"


def trusted_navigation(url: str, backend_url: str) -> bool:
    """The page with a native bridge may display only this launch's backend origin."""
    try:
        target, backend = urlsplit(url), urlsplit(backend_url)
        return (
            target.scheme == backend.scheme == "http"
            and target.hostname == backend.hostname == "127.0.0.1"
            and target.port == backend.port
            and target.username is None and target.password is None
        )
    except ValueError:
        return False


def bootstrap_script(origin: str, token: str, channel_js: str) -> str:
    """Defence in depth: never publish credentials to a foreign document."""
    return (
        "(() => { if (window.location.origin !== " + json.dumps(origin) + ") return;\n"
        + channel_js
        + f"\nwindow.__M4ML_TOKEN__={json.dumps(token)};window.__M4ML_DESKTOP__=true;"
        "window.m4mlReady=new Promise(function(res){new QWebChannel(qt.webChannelTransport,function(c){window.m4ml=c.objects.m4ml;res(window.m4ml);});});\n"
        "})();"
    )


def log(message):
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE / "desktop.log").open("a") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Backend:
    """Owns the API server process for the lifetime of the window."""

    def __init__(self, python):
        self.python = python
        self.port = int(os.environ.get("STUDIO_PORT") or free_port())
        self.token = secrets.token_urlsafe(32)
        self.url = f"http://127.0.0.1:{self.port}"
        self.proc = None

    def start(self):
        env = os.environ.copy()
        env.update(STUDIO_PARENT_PID=str(os.getpid()),
                   STUDIO_PARENT_START=Path(f"/proc/{os.getpid()}/stat").read_text().split()[21],
                   STUDIO_TOKEN=self.token, STUDIO_DESKTOP="1", OMP_NUM_THREADS=env.get("OMP_NUM_THREADS", "4"),
                   PYTHONUNBUFFERED="1")
        CACHE.mkdir(parents=True, exist_ok=True)
        self.log = (CACHE / "backend.log").open("a")
        self.log.write(f"\n=== start {time.strftime('%Y-%m-%d %H:%M:%S')} port {self.port}\n")
        self.log.flush()
        self.proc = subprocess.Popen(
            [self.python, "-m", "uvicorn", "studio.api:app", "--host", "127.0.0.1", "--port", str(self.port),
             "--no-access-log", "--timeout-graceful-shutdown", "10"],
            cwd=ROOT, env=env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        log(f"backend pid {self.proc.pid} port {self.port}")

    def ready(self, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                return False
            try:
                with urllib.request.urlopen(self.url + "/api/health", timeout=2) as r:
                    if json.load(r).get("app") == "M4ML Studio":
                        return True
            except Exception:
                time.sleep(0.3)
        return False

    def active_jobs(self):
        try:
            with urllib.request.urlopen(self.url + "/api/projects", timeout=3) as r:
                projects = json.load(r)
            running = []
            for p in projects:
                with urllib.request.urlopen(f"{self.url}/api/projects/{p['id']}", timeout=3) as r:
                    doc = json.load(r)
                running += [(doc["name"], j["stage"]) for j in doc.get("jobs", []) if j["state"] == "running"]
            return running
        except Exception:
            return []

    def stop(self):
        if not self.proc or self.proc.poll() is not None:
            return
        log("stopping backend")
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=25)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.proc.wait()
        log(f"backend exited {self.proc.returncode}")


def main(argv=None, *, application=None):
    from studio.desktop_dependencies import desktop_dependencies

    dependencies = desktop_dependencies()
    if dependencies["exit_code"]:
        print(dependencies["output"], file=sys.stderr)
        log(dependencies["output"])
        return 1
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--ignore-gpu-blocklist --enable-gpu-rasterization")
    from PySide6.QtCore import QObject, QSettings, QUrl, Slot, Qt, QStandardPaths
    from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import QWebEngineDownloadRequest, QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox, QSplashScreen
    from PySide6.QtGui import QPixmap, QFontDatabase

    if application is None:
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    # argv[0] sets the X11 WM_CLASS so the window groups with m4ml-studio.desktop
    app = application or QApplication(["m4ml-studio", *((argv or sys.argv)[1:])])
    font_file = ROOT / "frontend/public/fonts/NotoSansKR.ttf"
    if font_file.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_file))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            font = app.font()
            font.setFamily(families[0])
            app.setFont(font)
    # The product UI is Korean; Qt's own dialogs (file dialog buttons, overwrite confirmation)
    # use Qt's shipped Korean translations instead of English, independent of the OS locale.
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    QLocale.setDefault(QLocale(QLocale.Korean, QLocale.SouthKorea))
    app._m4ml_translators = []
    for name in ("qtbase_ko", "qt_ko"):
        translator = QTranslator(app)
        if translator.load(name, QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            app.installTranslator(translator)
            app._m4ml_translators.append(translator)
    app.setApplicationName("M4ML Studio")
    app.setOrganizationName("M4ML")
    app.setDesktopFileName("m4ml-studio")
    app.setWindowIcon(QIcon(str(ICON)))

    # ---- single instance: a second launch just raises the first window
    instance = "m4ml-studio-" + str(os.getuid())
    probe = QLocalSocket()
    probe.connectToServer(instance)
    if probe.waitForConnected(300):
        probe.write(b"raise")
        probe.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(instance)
    server = QLocalServer()
    server.listen(instance)

    splash = QSplashScreen(QPixmap(str(ROOT / "frontend/public/m4ml-logo.png")).scaledToWidth(520, Qt.SmoothTransformation))
    splash.showMessage("M4ML Studio를 시작하고 있습니다…", Qt.AlignBottom | Qt.AlignHCenter)
    splash.show()
    app.processEvents()

    backend = Backend(os.environ.get("STUDIO_PYTHON") or sys.executable)
    backend.start()
    if not backend.ready():
        splash.close()
        QMessageBox.critical(None, "M4ML Studio", f"처리 서버를 시작하지 못했습니다.\n로그: {CACHE / 'backend.log'}")
        backend.stop()
        return 1

    class Bridge(QObject):
        """Native functions callable from the UI (window.m4ml in JavaScript)."""

        def __init__(self, window):
            super().__init__()
            self.window = window

        @Slot(str, result=str)
        def pickFolder(self, title):
            return QFileDialog.getExistingDirectory(self.window, title or "폴더 선택", str(Path.home())) or ""

        @Slot(str, str, result=str)
        def pickFile(self, title, filters):
            path, _ = QFileDialog.getOpenFileName(self.window, title or "파일 선택", str(Path.home()), filters or "")
            return path or ""

        @Slot(str, result=bool)
        def openPath(self, path):
            if not path or not Path(path).exists():
                return False
            return QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path))))

        @Slot(result=str)
        def logFolder(self):
            return str(CACHE)

        @Slot()
        def toggleFullScreen(self):
            self.window.showNormal() if self.window.isFullScreen() else self.window.showFullScreen()

        @Slot(str)
        def setTitle(self, title):
            self.window.setWindowTitle(title + " — M4ML Studio" if title else "M4ML Studio")

        @Slot()
        def quit(self):
            self.window.close()

        @Slot(result=str)
        def info(self):
            return json.dumps({"desktop": True, "backend": backend.url, "log": str(CACHE), "qt": __import__("PySide6").__version__})

    class StudioPage(QWebEnginePage):
        def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
            # Applies to redirects, file/data URLs, dropped HTML and subframes too.
            # QWebChannel belongs to the page, so guarding the token script alone
            # cannot protect native methods from a document with its own channel JS.
            return trusted_navigation(url.toString(), backend.url)

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("M4ML Studio")
            self.setMinimumSize(1024, 640)
            self.settings = QSettings("M4ML", "M4ML Studio")
            # QObject destroys children in creation order. The view owns the page,
            # which must be released before its persistent WebEngine profile.
            self.view = QWebEngineView(self)
            profile = QWebEngineProfile("m4ml-studio", self)  # persistent: localStorage, layout, theme
            # Loopback assets are inexpensive; stale cached entry HTML can select
            # an old UI after an upgrade. Keep project/preferences storage only.
            profile.setHttpCacheType(QWebEngineProfile.NoCache)
            profile.setPersistentStoragePath(str(DATA / "webengine"))
            profile.setCachePath(str(CACHE / "webengine"))
            profile.downloadRequested.connect(self.download)
            page = StudioPage(profile, self.view)
            self.view.setPage(page)
            s = page.settings()
            s.setAttribute(QWebEngineSettings.WebGLEnabled, True)
            s.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
            s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
            s.setAttribute(QWebEngineSettings.FullScreenSupportEnabled, True)
            self.bridge = Bridge(self)
            channel = QWebChannel(page)
            channel.registerObject("m4ml", self.bridge)
            page.setWebChannel(channel)
            # inject token + qwebchannel bootstrap before any page script runs
            from PySide6.QtCore import QFile, QIODevice

            f = QFile(":/qtwebchannel/qwebchannel.js")
            f.open(QIODevice.ReadOnly)
            boot = bootstrap_script(backend.url, backend.token, bytes(f.readAll()).decode())
            script = QWebEngineScript()
            script.setName("m4ml-bootstrap")
            script.setSourceCode(boot)
            script.setInjectionPoint(QWebEngineScript.DocumentCreation)
            script.setWorldId(QWebEngineScript.MainWorld)
            script.setRunsOnSubFrames(False)
            page.scripts().insert(script)
            page.fullScreenRequested.connect(lambda r: (r.accept(), self.showFullScreen() if r.toggleOn() else self.showNormal()))
            self.setCentralWidget(self.view)
            self.view.load(QUrl(backend.url + "/"))
            geo = self.settings.value("geometry")
            if geo:
                self.restoreGeometry(geo)
            else:
                self.resize(1600, 960)
            QShortcut(QKeySequence("F11"), self, activated=self.bridge.toggleFullScreen)
            QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)

        def download(self, item):
            """Save an export exactly where the user chose.

            Qt's dialog already asks before replacing an existing file. The download goes to a
            hidden temporary file in the same folder and is moved onto the chosen path only
            after it completed, so an existing file survives a failed export and Chromium never
            silently renames the result ("name (1).ply")."""
            suggested = item.downloadFileName() or "download"
            folder = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or str(Path.home())
            start = str(Path(folder) / suggested)
            while True:
                path, _ = QFileDialog.getSaveFileName(self, "내보내기 저장", start)
                if not path:
                    item.cancel()
                    log("download cancelled")
                    return
                target = Path(path)
                if target.parent.is_dir() and os.access(target.parent, os.W_OK | os.X_OK) and not target.is_dir():
                    break
                QMessageBox.warning(self, "내보내기 저장",
                                    f"이 위치에는 저장할 수 없습니다. 쓰기 권한이 있는 다른 폴더를 선택하세요.\n{target.parent}")
                start = str(Path(folder) / target.name)
            temp = target.parent / f".{target.name}.{secrets.token_hex(4)}.part"
            item.setDownloadDirectory(str(target.parent))
            item.setDownloadFileName(temp.name)

            def finished():
                if not item.isFinished():
                    return
                if item.state() == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
                    try:
                        os.replace(temp, target)
                        log(f"download {target}")
                        return
                    except OSError as exc:
                        reason = str(exc)
                else:
                    reason = item.interruptReasonString() or "취소됨"
                temp.unlink(missing_ok=True)
                log(f"download failed {target}: {reason}")
                if item.state() != QWebEngineDownloadRequest.DownloadState.DownloadCancelled:
                    QMessageBox.warning(self, "내보내기 저장",
                                        f"파일을 저장하지 못했습니다. 기존 파일은 그대로 두었습니다.\n{target}\n\n원인: {reason}")

            item.isFinishedChanged.connect(finished)
            item.accept()

        def closeEvent(self, event):
            running = backend.active_jobs()
            if running:
                names = "\n".join(f"· {n}: {s}" for n, s in running)
                answer = QMessageBox.question(
                    self, "M4ML Studio 종료",
                    f"실행 중인 작업이 있습니다.\n{names}\n\n종료하면 작업을 중지합니다. 중간 결과와 기록은 보존되며, "
                    "학습은 마지막 저장 지점부터 이어서 할 수 있습니다. 종료할까요?")
                if answer != QMessageBox.Yes:
                    event.ignore()
                    return
            self.settings.setValue("geometry", self.saveGeometry())
            event.accept()
            QApplication.quit()

    window = Window()

    def raise_window():
        conn = server.nextPendingConnection()
        if conn:
            conn.readAll()
        window.showNormal()
        window.raise_()
        window.activateWindow()

    server.newConnection.connect(raise_window)
    # SIGTERM/SIGINT (logout, `kill`) take the same path as the window close button.
    from PySide6.QtCore import QTimer

    signal.signal(signal.SIGTERM, lambda *_: QTimer.singleShot(0, window.close))
    signal.signal(signal.SIGINT, lambda *_: QTimer.singleShot(0, window.close))
    tick = QTimer()
    tick.start(300)
    tick.timeout.connect(lambda: None)  # lets the Python interpreter handle signals
    window.show()
    splash.finish(window)
    try:
        code = app.exec()
    finally:
        backend.stop()
        server.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
