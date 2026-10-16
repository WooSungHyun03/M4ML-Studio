"""SQLite-authoritative projects/jobs/events with artifact manifests and invalidation."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import uuid

from studio.doctor import atomic_json

STAGES = ("import", "colmap", "sam", "review", "train", "mesh")
STATES = {
    "pending",
    "running",
    "waiting_for_user",
    "review_required",
    "completed",
    "failed",
    "cancelled",
    "blocked",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def data_root():
    if os.environ.get("STUDIO_DATA"):
        return Path(os.environ["STUDIO_DATA"]).expanduser().resolve()
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    legacy = base / "object-aware-studio"
    # Preserve existing installations in-place; new users get branded XDG storage.
    return (
        legacy if (legacy / "studio.sqlite").exists() else base / "m4ml-studio"
    ).resolve()


def invalidate(project, after):
    for stage in STAGES[STAGES.index(after) + 1 :]:
        project["stages"][stage] = "pending"
    project["revision"] += 1


class Store:
    def __init__(self, root=None):
        self.root = Path(root or data_root()).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Snapshot once per release before opening existing state; retain older backups.
        from studio.config import VERSION
        db_file = self.root / "studio.sqlite"
        backup = self.root / f"backups/pre-m4ml-{VERSION}.sqlite"
        if db_file.exists() and not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            import tempfile

            fd, temp = tempfile.mkstemp(prefix=".database-", dir=backup.parent)
            os.close(fd)
            try:
                with sqlite3.connect(db_file) as source, sqlite3.connect(
                    temp
                ) as destination:
                    source.backup(destination)
                os.replace(temp, backup)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        with self.db() as db:
            db.executescript(
                """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, stage TEXT NOT NULL,
              state TEXT NOT NULL, pid INTEGER, created TEXT NOT NULL, ended TEXT, request TEXT NOT NULL,
              message TEXT NOT NULL DEFAULT '', current INTEGER, total INTEGER, exit_code INTEGER,
              cancel_requested INTEGER NOT NULL DEFAULT 0);
            CREATE UNIQUE INDEX IF NOT EXISTS one_job_per_project ON jobs(project_id) WHERE state='running';
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
              created TEXT NOT NULL, payload TEXT NOT NULL);
            """
            )
            if "cancel_requested" not in {
                row[1] for row in db.execute("PRAGMA table_info(jobs)")
            }:
                db.execute(
                    "ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0"
                )

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.root / "studio.sqlite", timeout=20)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def path(self, project_id):
        try:
            canonical = str(uuid.UUID(project_id))
        except ValueError as exc:
            raise ValueError("프로젝트 주소가 유효하지 않습니다.") from exc
        if canonical != project_id:
            raise ValueError("프로젝트 주소가 유효하지 않습니다.")
        return self.root / "projects" / project_id

    def get(self, project_id):
        self.path(project_id)
        with self.db() as db:
            row = db.execute(
                "SELECT document FROM projects WHERE id=?", (project_id,)
            ).fetchone()
        if row is None:
            raise FileNotFoundError("프로젝트를 찾을 수 없습니다.")
        return json.loads(row[0])

    def list(self):
        with self.db() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT document FROM projects ORDER BY rowid DESC"
                )
            ]

    def create(self, name):
        name = name.strip()
        if not 1 <= len(name) <= 120:
            raise ValueError("프로젝트 이름을 1~120자로 입력하세요.")
        project_id = str(uuid.uuid4())
        p = {
            "schema_version": 1,
            "id": project_id,
            "name": name,
            "created": now(),
            "revision": 0,
            "stages": {stage: "pending" for stage in STAGES},
            "images": [],
            "import_errors": [],
            "masks": {},
            "target_confirmed": False,
            "settings": {"iterations": 30000},
        }
        self.path(project_id).mkdir(parents=True, mode=0o700)
        with self.db() as db:
            db.execute(
                "INSERT INTO projects VALUES (?,?)",
                (project_id, json.dumps(p, ensure_ascii=False)),
            )
        atomic_json(self.path(project_id) / "manifest.json", p)
        return p

    def update(self, project_id, mutate):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT document FROM projects WHERE id=?", (project_id,)
            ).fetchone()
            if not row:
                raise FileNotFoundError("프로젝트를 찾을 수 없습니다.")
            p = json.loads(row[0])
            mutate(p)
            if any(state not in STATES for state in p["stages"].values()):
                raise ValueError("프로젝트 상태가 유효하지 않습니다.")
            p["updated"] = now()
            db.execute(
                "UPDATE projects SET document=? WHERE id=?",
                (json.dumps(p, ensure_ascii=False), project_id),
            )
            db.execute(
                "INSERT INTO events(project_id,created,payload) VALUES (?,?,?)",
                (
                    project_id,
                    now(),
                    json.dumps({"stages": p["stages"], "revision": p["revision"]}),
                ),
            )
            # File write while holding DB lock prevents concurrent manifests reverting.
            atomic_json(self.path(project_id) / "manifest.json", p)
        return p

    def jobs(self, project_id):
        with self.db() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM jobs WHERE project_id=? ORDER BY created DESC",
                    (project_id,),
                )
            ]

    def job(self, job_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise FileNotFoundError("작업을 찾을 수 없습니다.")
        return dict(row)

    def active(self, project_id):
        return next((j for j in self.jobs(project_id) if j["state"] == "running"), None)

    def new_job(self, project_id, stage, request):
        job_id = str(uuid.uuid4())
        with self.db() as db:
            db.execute(
                "INSERT INTO jobs(id,project_id,stage,state,created,request) VALUES (?,?,?,'running',?,?)",
                (job_id, project_id, stage, now(), json.dumps(request)),
            )
        return job_id

    def job_update(self, job_id, **values):
        if set(values) - {
            "pid",
            "state",
            "ended",
            "message",
            "current",
            "total",
            "exit_code",
            "cancel_requested",
        }:
            raise ValueError("invalid job fields")
        with self.db() as db:
            db.execute(
                "UPDATE jobs SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?",
                (*values.values(), job_id),
            )

    def reconcile(self):
        # App lifecycle owns workers. Only signal a PID whose command contains
        # both our worker module and this job's unpredictable UUID.
        import signal

        for p in self.list():
            job = self.active(p["id"])
            if job:
                pid = job["pid"]
                try:
                    command = Path(f"/proc/{pid}/cmdline").read_bytes() if pid else b""
                    if b"studio.worker" in command and job["id"].encode() in command:
                        from studio.process import signal_owned_worker

                        signal_owned_worker(pid, job["id"])
                        # Recovery will refuse duplicate workers until confirmed dead.
                        import time

                        for _ in range(100):
                            try:
                                os.kill(pid, 0)
                            except ProcessLookupError:
                                break
                            if Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z":
                                break
                            time.sleep(0.1)
                        else:
                            raise RuntimeError(
                                "이전 작업이 종료 중입니다. 잠시 후 다시 실행하세요."
                            )
                except FileNotFoundError:
                    pass
                self.job_update(
                    job["id"],
                    state="cancelled",
                    ended=now(),
                    message="앱 재시작으로 중단되었습니다. 로그를 확인하고 다시 실행하세요.",
                )
                stage = job["stage"]
                self.update(
                    p["id"],
                    lambda doc: doc["stages"].update(
                        {"sam" if stage == "preview" else stage: "cancelled"}
                    ),
                )
            self.audit_artifacts(p["id"])

    def audit_artifacts(self, project_id):
        """A durable flag is insufficient: re-check completed artifact contracts."""
        from studio.colmap import validate_scene
        from studio.sam31 import validate_mask
        from studio.doctor import sha256
        from PIL import Image

        p = self.get(project_id)
        root = self.path(project_id)

        def fail(stage, message):
            def update(doc):
                invalidate(doc, stage)
                doc["stages"][stage] = "failed"
                doc.setdefault("integrity_errors", []).append(
                    {"stage": stage, "message": message, "time": now()}
                )

            self.update(project_id, update)

        if p["stages"]["colmap"] == "completed":
            try:
                names = validate_scene(root / p["scene"])
            except Exception as exc:
                fail("colmap", f"재시작 시 재구성 결과 검증에 실패했습니다: {exc}")
                return
            invalid = {}
            if p["stages"]["sam"] == "completed":
                for name in names:
                    item = p["masks"].get(name, {})
                    try:
                        with Image.open(root / p["scene"] / "images" / name) as image:
                            stats = validate_mask(root / item["path"], image.size)
                        if stats["sha256"] != item["sha256"]:
                            raise ValueError("저장된 마스크가 변경되었습니다.")
                    except Exception as exc:
                        invalid[name] = {
                            **item,
                            "valid": False,
                            "status": "invalid",
                            "error": str(exc),
                        }
                if invalid:

                    def update(doc):
                        doc["masks"].update(invalid)
                        invalidate(doc, "review")
                        doc["stages"]["review"] = "review_required"

                    self.update(project_id, update)
                    return
        if p["stages"]["train"] == "completed":
            try:
                training = p["training"]
                path = root / training["path"]
                if not (path / "cfg_args").is_file():
                    raise ValueError("학습 설정 파일이 없습니다.")
                ply = (
                    path
                    / "point_cloud"
                    / f"iteration_{training['iterations']}"
                    / "point_cloud.ply"
                )
                from plyfile import PlyData
                import numpy as np

                vertices = PlyData.read(ply)["vertex"]
                if not len(vertices) or not all(
                    np.isfinite(vertices[k]).all() for k in ("x", "y", "z")
                ):
                    raise ValueError("가우시안 결과가 유효하지 않습니다.")
                if training.get("ply_sha256") and sha256(ply) != training["ply_sha256"]:
                    raise ValueError("학습 파일이 변경되었습니다.")
            except Exception as exc:
                fail("train", f"학습 결과 검증에 실패했습니다: {exc}")
                return
        if p["stages"]["mesh"] == "completed":
            try:
                from studio.mesh import validate_mesh

                mesh = root / p["mesh"]["path"]
                if not (mesh / "preview.glb").is_file():
                    raise ValueError("메시 미리보기 파일이 없습니다.")
                report = validate_mesh(mesh / "fuse_post.ply")
                if report["sha256"] != p["mesh"]["sha256"]:
                    raise ValueError("메시 파일이 변경되었습니다.")
                if p["mesh"].get("exporter_version", 0) < 3:
                    # Preserve legacy GLB; write a corrected portable color preview beside it.
                    report = validate_mesh(mesh / "fuse_post.ply", mesh / "color-v3")
                    self.update(
                        project_id,
                        lambda doc: doc["mesh"].update(
                            {
                                **report,
                                "preview_name": "color-v3/preview.glb",
                                "preview_color_version": 3,
                            }
                        ),
                    )
            except Exception as exc:
                fail("mesh", f"메시 결과 검증에 실패했습니다: {exc}")
