import base64
from contextlib import asynccontextmanager, contextmanager
import fcntl
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import time

from fastapi import FastAPI, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ConfigDict, model_validator
from PIL import Image

from studio.colmap import validate_scene
from studio.dispatch import launch
from studio.doctor import ROOT
from studio.importer import import_image, atomic_bytes, MAX_FILE
from studio.sam31 import validate_mask
from studio.store import Store, invalidate

# The desktop shell generates the token and injects it into its own window only;
# in that mode /api/session is disabled so other local pages cannot discover it.
TOKEN = os.environ.get("STUDIO_TOKEN") or secrets.token_urlsafe(32)
DESKTOP = os.environ.get("STUDIO_DESKTOP") == "1"
store = Store()


def _watch_desktop_parent():
    """In desktop mode the backend must not outlive its window process (even after SIGKILL)."""
    pid, start = os.environ.get("STUDIO_PARENT_PID"), os.environ.get("STUDIO_PARENT_START")
    if not pid:
        return
    import threading

    def loop():
        while True:
            time.sleep(1)
            try:
                alive = Path(f"/proc/{pid}/stat").read_text().split()[21] == start
            except (OSError, IndexError):
                alive = False
            if not alive:
                os.kill(os.getpid(), signal.SIGTERM)  # graceful: lifespan stops jobs/sessions
                return

    threading.Thread(target=loop, daemon=True).start()


@asynccontextmanager
async def lifespan(app):
    from studio.live_prompt import reset, stop_all

    reset()
    store.reconcile()
    _watch_desktop_parent()
    yield
    stop_all()
    from studio import segmentation_session

    segmentation_session.release()
    from studio import live_render

    live_render.release()
    for project in store.list():
        active = store.active(project["id"])
        if active and active["pid"]:
            try:
                os.kill(active["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass


app = FastAPI(title="M4ML Studio", lifespan=lifespan)


@app.middleware("http")
async def local_only(request: Request, call_next):
    host = request.headers.get("host", "").split(":")[0]
    if host not in {"127.0.0.1", "localhost", "testserver"}:
        return JSONResponse(
            {"detail": "로컬 주소로만 접속할 수 있습니다."}, status_code=403
        )
    origin = request.headers.get("origin")
    if origin and origin not in {
        f"http://{request.headers.get('host')}",
        f"https://{request.headers.get('host')}",
    }:
        return JSONResponse(
            {"detail": "다른 사이트의 요청은 허용하지 않습니다."}, status_code=403
        )
    if (
        request.method not in {"GET", "HEAD", "OPTIONS"}
        and request.headers.get("x-studio-token") != TOKEN
    ):
        return JSONResponse(
            {"detail": "앱을 새로고침한 뒤 다시 시도하세요."}, status_code=403
        )
    limit = MAX_FILE + 1024 * 1024
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        return JSONResponse(
            {"detail": "요청 크기가 유효하지 않습니다."}, status_code=400
        )
    if declared > limit:
        return JSONResponse(
            {"detail": "요청 파일이 너무 큽니다. 128MB 이하 사진을 선택하세요."},
            status_code=413,
        )
    consumed = 0
    original_receive = request._receive

    async def bounded_receive():
        nonlocal consumed
        message = await original_receive()
        consumed += len(message.get("body", b""))
        if consumed > limit:
            raise HTTPException(413, "요청 크기 제한을 초과했습니다.")
        return message

    request._receive = bounded_receive
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    # Pydantic's raw `input` can contain NaN/Infinity from invalid JSON numbers,
    # and `ctx` may contain an exception. Neither is safe to echo as JSON.
    detail = [{k: error[k] for k in ("loc", "msg", "type") if k in error} for error in exc.errors()]
    return JSONResponse({"detail": detail}, status_code=422)


@app.exception_handler(FileNotFoundError)
async def missing(request, exc):
    return JSONResponse(
        {
            "detail": f"필요한 파일을 찾을 수 없습니다. 프로젝트 파일을 확인하세요. {getattr(exc,'filename',None) or str(exc)}"
        },
        status_code=404,
    )


@contextmanager
def editable(project_id):
    root = store.path(project_id)
    store.get(project_id)
    with (root / ".edit.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if store.active(project_id):
            raise HTTPException(409, "실행 중인 작업을 먼저 중지하세요.")
        yield store.get(project_id), root


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Name(Strict):
    name: str = Field(min_length=1, max_length=120)


class Create(Name):
    input_mode: str = "images"


class Job(Strict):
    session_id: str | None = Field(default=None, max_length=64)
    prompt_revision: int | None = Field(default=None, ge=0)
    radius: int | None = Field(default=None, ge=1, le=25)
    gpu: int = Field(default=0, ge=0, le=31)
    reference: str | None = None
    points: list[list[float]] = Field(default_factory=list, max_length=1000)
    labels: list[int] = Field(default_factory=list, max_length=1000)
    confirmed: bool = False
    iterations: int = Field(default=30000, ge=100, le=100000)
    mesh_res: int = Field(default=1024, ge=64, le=2048)
    matching: str = "exhaustive"
    component: str | None = None
    resolution: int = Field(default=-1, ge=-1, le=8192)
    # Camera reconstruction without GPU acceleration must be chosen explicitly.
    cpu_fallback: bool = False
    # Continue an interrupted reconstruction from its last saved checkpoint.
    resume: bool = False


class Mask(Strict):
    png: str | None = Field(default=None, max_length=50000000)
    approve: bool = True


class Confirm(Strict):
    confirmed: bool


@app.get("/api/session")
def session():
    if DESKTOP:
        raise HTTPException(403, "데스크톱 앱 창에서만 사용할 수 있습니다.")
    return {"token": TOKEN}


from functools import lru_cache


@lru_cache(maxsize=1)
def runtime_status():
    script = "import json,torch;print(json.dumps(dict(torch=torch.__version__,cuda=torch.version.cuda,available=torch.cuda.is_available(),anchor_ok=torch.__version__.split('+')[0]=='2.5.1' and torch.version.cuda=='11.8')))"
    try:
        result = subprocess.run(
            [os.sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, subprocess.SubprocessError):
        return {
            "available": False,
            "anchor_ok": False,
            "error": "GPU 런타임이 없거나 호환되지 않습니다. 설치·진단 안내를 확인하세요.",
        }


@app.get("/api/health")
def health():
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.free,uuid,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        gpus = []
        for line in result.stdout.splitlines():
            i, name, total, free, uuid, driver = [v.strip() for v in line.split(",")]
            gpus.append(
                {
                    "index": int(i),
                    "name": name,
                    "total_mb": int(total),
                    "free_mb": int(free),
                    "uuid": uuid,
                    "driver": driver,
                }
            )
        error = None
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        gpus = []
        error = str(exc)
    return {
        "app": "M4ML Studio",
        "version": __import__("studio.config", fromlist=["VERSION"]).VERSION,
        "gpus": gpus,
        "gpu_error": error,
        "colmap": camera_engine_status(),
        "disk_free": shutil.disk_usage(store.root).free,
        "runtime": str(Path(os.sys.executable)),
        "runtime_status": runtime_status(),
        "checkpoint_exists": checkpoint().is_file(),
    }


def checkpoint():
    from studio.engines import provider

    return provider("segmentation").checkpoint()


def camera_engine_status():
    """Is a camera reconstruction engine usable, and does it have GPU support?"""
    from studio.engines import colmap_binary

    try:
        path, probe, origin = colmap_binary()
        return {"available": True, "gpu": bool(probe.get("cuda")), "origin": origin}
    except RuntimeError as exc:
        return {"available": False, "gpu": False, "error": str(exc)}


@app.get("/api/engines")
def engines_info():
    """Advanced information: engines, versions, paths, verification and licenses."""
    from studio.engines import all_info, config
    from studio import segmentation_session

    h = health()
    return {
        "engines": all_info(),
        "configuration": config(),
        "runtime": h["runtime_status"],
        "runtime_path": h["runtime"],
        "gpus": h["gpus"],
        "live_sessions": segmentation_session.status(),
        "live_render": __import__("studio.live_render", fromlist=["status"]).status(),
        "licenses": [
            {"component": "Object-Aware Loss / 2DGS / Gaussian-Splatting", "license": "비상업적 연구·평가 전용 (licenses/)", "commercial": False},
            {"component": "SIBR remote viewer (Gaussian-Splatting-Monitor, 외부 뷰어)", "license": "Inria 비상업적 연구·평가 전용 (runtime/sibr/licenses/)", "commercial": False},
            {"component": "SAM 3.1 코드·체크포인트", "license": "SAM License (licenses/), 체크포인트 이용 조건 별도 확인", "commercial": None},
            {"component": "COLMAP 자체", "license": "BSD-3-Clause (종속 라이브러리 별도)", "commercial": True},
            {"component": "내장 정합 런타임 종속 라이브러리", "license": "SuiteSparse GPL/LGPL 포함. 소스 제공·재링크·결합 배포 검토 미완료. 공개 배포 보류", "commercial": None},
            {"component": "M4ML Studio 앱 코드", "license": "LICENSE.md 참조", "commercial": None},
        ],
    }


class CheckpointPath(Strict):
    path: str = Field(min_length=1, max_length=4096)


@app.put("/api/settings/checkpoint")
def configure_checkpoint(body: CheckpointPath):
    from studio.config import save_settings

    path = Path(body.path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in {".pt", ".pth"}:
        raise ValueError("객체 선택 모델 파일(.pt) 경로를 지정하세요.")
    if not 1024**3 < path.stat().st_size < 10 * 1024**3:
        raise ValueError(
            "모델 파일 크기가 예상과 다릅니다. 올바른 파일인지 확인하세요. 모델 구조는 처음 사용할 때 다시 검사합니다."
        )
    save_settings({"checkpoint": str(path)})
    save_settings({"engines": {"segmentation": {"options": {"checkpoint": str(path)}}}})
    return {
        "configured": True,
        "bytes": path.stat().st_size,
        "note": "실제 모델 구조/추론 검증은 별도입니다.",
    }


@app.post("/api/shutdown")
def shutdown():
    from studio.live_prompt import stop_all
    import threading

    stop_all()
    from studio import segmentation_session

    segmentation_session.release()
    from studio import live_render

    live_render.release()
    threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return {"message": "실행 작업을 정리하고 M4ML Studio를 종료합니다."}


@app.get("/api/diagnostics")
def diagnostics():
    import platform
    from studio.config import VERSION

    # No user filenames, home directories or project logs in this portable report.
    h = health()
    return {
        "app": "M4ML Studio",
        "version": VERSION,
        "os": platform.platform(),
        "python": platform.python_version(),
        "gpus": [
            {key: value for key, value in g.items() if key != "uuid"} for g in h["gpus"]
        ],
        "gpu_available": bool(h["gpus"]),
        "colmap_available": h["colmap"].get("available"),
        "camera_gpu": h["colmap"].get("gpu"),
        "checkpoint_present": h["checkpoint_exists"],
        "runtime_status": h["runtime_status"],
        "free_disk_gb": round(h["disk_free"] / 1024**3, 1),
        "privacy": "프로젝트 경로·이미지·프롬프트·로그 원문 제외",
    }


@app.get("/api/projects")
def projects():
    return store.list()


@app.post("/api/projects")
def create(body: Create):
    if body.input_mode not in {"images", "colmap", "colmap_masks", "mesh"}:
        raise ValueError("시작 방식을 선택하세요.")
    p = store.create(body.name)
    return store.update(p["id"], lambda doc: doc.update(input_mode=body.input_mode))


@app.get("/api/projects/{project_id}")
def project(project_id: str):
    p = store.get(project_id)
    p["project_path"] = str(store.path(project_id))
    p["jobs"] = store.jobs(project_id)
    return p


@app.patch("/api/projects/{project_id}")
def rename(project_id: str, body: Name):
    if not body.name.strip():
        raise ValueError("프로젝트 이름을 입력하세요.")
    with editable(project_id):
        return store.update(project_id, lambda p: p.update(name=body.name.strip()))


@app.delete("/api/projects/{project_id}")
def archive(project_id: str):
    with editable(project_id):
        return store.update(project_id, lambda p: p.update(archived=True))


@app.post("/api/projects/{project_id}/restore")
def restore(project_id: str):
    with editable(project_id):
        return store.update(project_id, lambda p: p.update(archived=False))


@app.post("/api/projects/{project_id}/images")
def upload(project_id: str, file: UploadFile):
    with editable(project_id) as (p, root):
        if p["stages"]["import"] == "completed":
            raise ValueError(
                "새 사진은 새 프로젝트로 불러오세요. 기존 재구성 자료는 보존됩니다."
            )
        if len(p["images"]) >= 2000:
            raise ValueError("프로젝트당 최대 2,000장까지 불러올 수 있습니다.")
        if shutil.disk_usage(root).free < 1024**3:
            raise ValueError("남은 저장 공간이 1GB보다 작습니다.")
        data = file.file.read(MAX_FILE + 1)
        try:
            item = import_image(
                root,
                data,
                file.filename or "이름 없는 사진",
                len(p["images"]) + 1,
                p["images"],
            )
        except (
            ValueError,
            OSError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            message = str(exc)
            store.update(
                project_id,
                lambda doc: doc["import_errors"].append(
                    {"name": file.filename, "error": message}
                ),
            )
            raise ValueError(f"사진을 불러오지 못했습니다: {message}") from exc
        return store.update(project_id, lambda doc: doc["images"].append(item))


@app.post("/api/projects/{project_id}/import-complete")
def complete_import(project_id: str):
    with editable(project_id) as (p, root):
        if p["stages"]["import"] == "completed":
            return p
        if len([i for i in p["images"] if not i["duplicate_of"]]) < 2:
            raise ValueError(
                "서로 다른 사진이 2장 이상 필요합니다. 안정적인 재구성에는 더 많은 사진을 권장합니다."
            )
        store.update(
            project_id, lambda doc: doc["stages"].update({"import": "completed"})
        )
        # Start camera registration automatically only when GPU acceleration is really
        # available; a CPU run is never started without the user's explicit choice.
        engine = camera_engine_status()
        gpus = health()["gpus"] if engine.get("gpu") else []
        if not gpus:
            store.update(project_id, lambda doc: doc["stages"].update({"colmap": "waiting_for_user"}))
            return {"job_id": None, "message": "GPU 가속 카메라 정합을 사용할 수 없습니다. 카메라 정합 단계에서 실행 방식을 선택하세요."}
        from studio import segmentation_session

        segmentation_session.release(gpus[0].get("uuid", "0"))
        from studio import live_render

        live_render.release(gpus[0].get("uuid", "0"))
        return {
            "job_id": launch(store, project_id, "colmap", {
                "matching": "exhaustive", "gpu": gpus[0]["index"], "gpu_uuid": gpus[0].get("uuid", "0")})
        }


def preflight(p, root):
    if not p.get("scene") or p["stages"]["colmap"] != "completed":
        return {
            "valid": False,
            "failures": [
                {"name": "카메라 등록", "reason": "재구성을 먼저 완료하세요."}
            ],
            "images": 0,
            "disk_free": shutil.disk_usage(root).free,
            "default_iterations": 30000,
        }
    names = validate_scene(root / p["scene"])
    failures = []
    for name in sorted(names):
        item = p["masks"].get(name, {})
        try:
            if item.get("status") not in {"approved", "manual", "skipped"}:
                raise ValueError("검토 또는 명시적 생략이 필요합니다.")
            with Image.open(root / p["scene"] / "images" / name) as image:
                stats = validate_mask(root / item["path"], image.size)
            if stats["sha256"] != item["sha256"]:
                raise ValueError("마스크 파일이 변경되었습니다.")
        except (ValueError, KeyError, OSError) as exc:
            failures.append({"name": name, "reason": str(exc)})
    coverage = [
        item.get("coverage", 0) for item in p["masks"].values() if item.get("valid")
    ]
    return {
        "valid": not failures and p["target_confirmed"],
        "failures": failures,
        "images": len(names),
        "mask_coverage_min": min(coverage) if coverage else None,
        "mask_coverage_max": max(coverage) if coverage else None,
        "disk_free": shutil.disk_usage(root).free,
        "default_iterations": 30000,
    }


class ImportOptions(Strict):
    with_masks: bool = False
    sparse: str | None = None
    images: str | None = None
    masks: str | None = None
    normalize_masks: bool = False
    mask_channel: str = "gray"
    foreground: str = "white"
    skip_review: bool = False


@app.post("/api/projects/{project_id}/import-files")
async def upload_import_file(project_id: str, file: UploadFile):
    from pathlib import PurePosixPath
    from studio.colmap_import import safe

    with editable(project_id) as (p, root):
        if p["images"] or p.get("scene"):
            raise ValueError("새 프로젝트에서만 기존 데이터를 가져올 수 있습니다.")
        relative = PurePosixPath(file.filename or "")
        if (
            relative.is_absolute()
            or any(x in {"..", "."} for x in relative.parts)
            or "\\" in str(relative)
            or len(str(relative)) > 2048
        ):
            raise ValueError("파일 경로가 유효하지 않습니다.")
        if relative.suffix.lower() not in {
            ".bin",
            ".txt",
            ".png",
            ".jpg",
            ".jpeg",
            ".tif",
            ".tiff",
        }:
            raise ValueError("지원하지 않는 가져오기 파일 형식입니다.")
        target = safe(root / "import-upload", relative.as_posix())
        data = await file.read(MAX_FILE + 1)
        if len(data) > MAX_FILE or not data:
            raise ValueError("비어 있거나128MB를 초과한 파일입니다.")
        if len(list((root / "import-upload").rglob("*"))) > 20000:
            raise ValueError("가져올 파일 수가 너무 많습니다.")
        if shutil.disk_usage(root).free < len(data) + 512 * 1024**2:
            raise ValueError("저장 공간이 부족합니다.")
        atomic_bytes(target, data)
        return {"path": str(relative), "bytes": len(data)}


@app.post("/api/projects/{project_id}/inspect-import")
def inspect_import(project_id: str, body: ImportOptions):
    from studio.colmap_import import inspect_colmap_import
    import uuid

    with editable(project_id) as (p, root):
        return inspect_colmap_import(
            root / "import-upload",
            body.model_dump(),
            root / "import-audits" / str(uuid.uuid4()),
        )


@app.post("/api/projects/{project_id}/commit-import")
def import_existing(project_id: str, body: ImportOptions):
    from studio.colmap_import import commit_import

    with editable(project_id) as (p, root):
        if p["images"] or p.get("scene"):
            raise ValueError("새 프로젝트에서만 기존 데이터를 가져올 수 있습니다.")
        if body.foreground not in {"white", "black"} or body.mask_channel not in {
            "gray",
            "alpha",
        }:
            raise ValueError("전경 색상과 마스크 채널을 선택하세요.")
        result = commit_import(root, body.model_dump())
        if not result["committed"]:
            return result

        def finish(doc):
            for key in ("scene", "images", "masks", "colmap_report"):
                doc[key] = result[key]
            doc["stage_provenance"] = {
                key: result["provenance"] for key in ("import", "colmap")
            }
            doc["input_mode"] = "colmap_masks" if body.with_masks else "colmap"
            invalidate(doc, "colmap")
            doc["stages"].update(
                {
                    "import": "completed",
                    "colmap": "completed",
                    "sam": "completed" if body.with_masks else "waiting_for_user",
                    "review": "review_required" if body.with_masks else "pending",
                }
            )
            if body.with_masks:
                doc["target_confirmed"] = True
                doc["stage_provenance"]["sam"] = result["provenance"]
                if body.skip_review:
                    for m in doc["masks"].values():
                        m.update(status="skipped", review_source="explicit_import_skip")
                    doc["stages"]["review"] = "completed"
                    doc["stage_provenance"]["review"] = {
                        **result["provenance"],
                        "skip_reason": "explicit_import_skip",
                    }
            if body.with_masks:
                invalidate(doc, "review")

        result["project"] = store.update(project_id, finish)
        return result


@app.post("/api/projects/{project_id}/mesh-file")
async def import_mesh_file(project_id: str, file: UploadFile):
    from studio.mesh import validate_mesh
    import uuid

    with editable(project_id) as (p, root):
        if p["images"] or p.get("mesh"):
            raise ValueError("새 결과 프로젝트에서 메시를 여세요.")
        extension = Path(file.filename or "").suffix.lower()
        if extension not in {".ply", ".glb"}:
            raise ValueError("삼각형 PLY 또는 GLB를 선택하세요.")
        data = await file.read(MAX_FILE + 1)
        if not data or len(data) > MAX_FILE:
            raise ValueError("128MB 이하의 메시를 선택하세요.")
        work = root / "mesh-import" / str(uuid.uuid4())
        work.mkdir(parents=True)
        source = work / ("source" + extension)
        atomic_bytes(source, data)
        from studio.mesh import validate_mesh

        report = validate_mesh(source, work)
        if extension == ".ply":
            shutil.copyfile(source, work / "fuse_post.ply")
        else:
            import trimesh
            from studio.mesh import glb_colors, linear_to_srgb
            import numpy as np

            mesh = trimesh.load(source, force="mesh", process=False)
            colors = glb_colors(source)
            if colors is not None:
                mesh.visual.vertex_colors = np.column_stack(
                    [
                        np.rint(np.clip(linear_to_srgb(colors), 0, 1) * 255).astype(
                            np.uint8
                        ),
                        np.full(len(colors), 255, np.uint8),
                    ]
                )
            mesh.export(work / "fuse_post.ply")
        report = validate_mesh(work / "fuse_post.ply", work)

        def finish(doc):
            doc["mesh"] = {
                **report,
                "path": str(work.relative_to(root)),
                "source_name": file.filename,
            }
            doc["stages"]["mesh"] = "completed"
            doc["input_mode"] = "mesh"
            doc["stage_provenance"] = {
                "mesh": {
                    "stage_source": "imported",
                    "stage_state": "verified",
                    "skip_reason": "existing_valid_output",
                }
            }

        return store.update(project_id, finish)


class FolderPath(Strict):
    path: str = Field(min_length=1, max_length=4096)


class FolderOpen(FolderPath):
    name: str | None = Field(default=None, max_length=120)
    sparse: str | None = None
    images: str | None = None
    masks: str | None = None
    use_training: bool = True
    use_mesh: bool = True


def _folder(path):
    folder = Path(path).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError("폴더를 찾을 수 없습니다.")
    if folder == Path.home().resolve() or folder == Path("/") or len(folder.parts) < 3:
        raise ValueError("홈 폴더나 시스템 폴더 전체는 열 수 없습니다. 프로젝트 데이터 폴더를 선택하세요.")
    return folder


@app.post("/api/scan-folder")
def scan_folder_api(body: FolderPath):
    """Read-only analysis of a user-selected folder (see studio/project_scan.py)."""
    from studio.project_scan import scan_folder

    result = scan_folder(_folder(body.path))
    existing = (result.get("manifest") or {}).get("id")
    if existing:
        try:
            store.get(existing)
            result["existing_project"] = existing
        except (FileNotFoundError, ValueError):
            pass
    return result


@app.post("/api/projects/from-folder")
def open_folder(body: FolderOpen):
    """Create a project from a folder, reusing every valid existing result in it.

    The folder is never modified: photos, calibration, masks, training outputs and meshes
    that pass validation are copied into the project; invalid or foreign results are skipped
    with a reason. Returns the project plus what was reused."""
    from studio.project_scan import scan_folder
    import uuid

    folder = _folder(body.path)
    scan = scan_folder(folder)
    existing = (scan.get("manifest") or {}).get("id")
    if existing:
        try:
            return {"project": store.get(existing), "reused": ["기존 M4ML Studio 프로젝트"], "skipped": []}
        except (FileNotFoundError, ValueError):
            pass
    rec = scan["recommendation"]["stage"]
    if rec is None:
        raise ValueError(scan["problems"][0])
    sparse = body.sparse or scan["selected_sparse"]
    masks_ok = bool(scan.get("masks") and scan["masks"].get("complete")) and not body.sparse
    mesh_only = not sparse and not scan.get("images") and scan["meshes"]
    mode = "mesh" if mesh_only else ("colmap_masks" if sparse and masks_ok else "colmap" if sparse else "images")
    p = store.create((body.name or folder.name)[:120] or "새 프로젝트")
    pid, root = p["id"], store.path(p["id"])
    reused, skipped = [], list(scan["problems"])
    store.update(pid, lambda doc: doc.update(input_mode=mode, source_folder=str(folder)))
    try:
        if mesh_only:
            _import_mesh(pid, folder / scan["meshes"][0]["path"], None)
            reused.append("3D 모델 " + scan["meshes"][0]["path"])
        elif sparse:
            from studio.colmap_import import commit_import

            options = {"with_masks": masks_ok, "sparse": sparse,
                       "images": body.images or next((x.get("images_dir") for x in scan["sparse"] if x["path"] == sparse), None),
                       "masks": body.masks or (scan["masks"]["dir"] if masks_ok else None),
                       "foreground": "white", "mask_channel": "gray", "normalize_masks": False, "skip_review": masks_ok}
            result = commit_import(root, options, source=folder)
            if not result["committed"]:
                audit = result["audit"]
                raise ValueError("기존 카메라 정합 결과를 가져오지 못했습니다: " + "; ".join(
                    (audit.get("blocking_errors") or []) + [e["error"] for e in audit.get("mask_errors") or []][:5]))

            def finish(doc):
                for key in ("scene", "images", "masks", "colmap_report"):
                    doc[key] = result[key]
                doc["stage_provenance"] = {key: result["provenance"] for key in ("import", "colmap")}
                invalidate(doc, "colmap")
                doc["stages"].update({"import": "completed", "colmap": "completed",
                                      "sam": "completed" if masks_ok else "waiting_for_user",
                                      "review": "completed" if masks_ok else "pending"})
                if masks_ok:
                    doc["target_confirmed"] = True
                    doc["stage_provenance"]["sam"] = result["provenance"]
                    doc["stage_provenance"]["review"] = {**result["provenance"], "skip_reason": "existing_folder_masks"}
                    for m in doc["masks"].values():
                        m.update(status="skipped", review_source="existing_folder_masks")

            store.update(pid, finish)
            reused.append(f"카메라 정합 결과 ({result['colmap_report']['registered']}장 등록)")
            if masks_ok:
                reused.append(f"객체 마스크 {len(result['masks'])}장")
            if masks_ok and body.use_training:
                reused += _import_training(pid, folder, scan, skipped, body.use_mesh)
        else:
            images_dir = folder / (body.images or scan["images"]["dir"])
            count = 0
            for f in sorted(images_dir.iterdir()):
                if f.suffix.lower() not in {".jpg", ".jpeg", ".png", ".tif", ".tiff"} or not f.is_file():
                    continue
                doc = store.get(pid)
                try:
                    item = import_image(root, f.read_bytes(), f.name, len(doc["images"]) + 1, doc["images"])
                    store.update(pid, lambda d, item=item: d["images"].append(item))
                    count += 1
                except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                    store.update(pid, lambda d, n=f.name, e=str(exc): d["import_errors"].append({"name": n, "error": e}))
            reused.append(f"사진 {count}장")
            if count >= 2:
                started = complete_import(pid)
                if isinstance(started, dict) and started.get("job_id"):
                    reused.append("카메라 정합 자동 시작 (GPU)")
    except Exception:
        store.update(pid, lambda doc: doc.update(open_folder_error=True))
        raise
    store.update(pid, lambda doc: doc.update(folder_import={"reused": reused, "skipped": skipped,
                                                             "recommendation": scan["recommendation"]}))
    out = store.get(pid)
    out["project_path"] = str(root)
    return {"project": out, "reused": reused, "skipped": skipped}


def _import_training(pid, folder, scan, skipped, use_mesh):
    """Copy a training output that verifiably belongs to this dataset into the project."""
    import uuid
    from plyfile import PlyData
    import numpy as np
    from studio.doctor import sha256 as file_sha

    candidates = [t for t in scan["training"] if t.get("valid") and t.get("dataset_match") == "yes"]
    if not candidates:
        return []
    t = max(candidates, key=lambda t: (max(t.get("iterations") or [0]), max(t.get("checkpoints") or [0])))
    root = store.path(pid)
    src = folder / t["path"]
    dest = root / "runs" / f"imported-{uuid.uuid4()}" / "training"
    dest.mkdir(parents=True)
    for name in ("cfg_args", "cameras.json", "input.ply"):
        if (src / name).is_file():
            shutil.copyfile(src / name, dest / name)
    used = []
    if t.get("iterations"):
        last = t["iterations"][-1]
        shutil.copytree(src / "point_cloud" / f"iteration_{last}", dest / "point_cloud" / f"iteration_{last}")
        ply = dest / "point_cloud" / f"iteration_{last}" / "point_cloud.ply"
        vertices = PlyData.read(ply)["vertex"]
        if not len(vertices) or not all(np.isfinite(vertices[k]).all() for k in ("x", "y", "z")):
            skipped.append("가져온 학습 결과에 유효한 가우시안이 없어 사용하지 않았습니다.")
            return []

        def finish(doc):
            doc["training"] = {"path": str(dest.relative_to(root)), "iterations": last, "revision": doc["revision"],
                               "gaussians": len(vertices), "gpu": 0, "ply_sha256": file_sha(ply),
                               "engine": "object_aware_2dgs", "imported_from": str(src)}
            doc["stages"]["train"] = "completed"
            doc.setdefault("stage_provenance", {})["train"] = {"stage_source": "imported", "stage_state": "verified",
                                                              "skip_reason": "existing_valid_output"}

        store.update(pid, finish)
        used.append(f"학습 결과 {last:,}회 (가우시안 {len(vertices):,}개)")
        meshes = [m for m in scan["meshes"] if m.get("valid") and m.get("kind") == "ply" and m["path"].startswith(t["path"] + "/") and m.get("colors")]
        if use_mesh and meshes:
            _import_mesh(pid, folder / meshes[0]["path"], last)
            used.append(f"3D 모델 ({meshes[0]['triangles']:,} 삼각형)")
    elif t.get("checkpoints"):
        last = t["checkpoints"][-1]
        if last >= 30000:
            skipped.append("저장 지점이 이미 기본 학습 횟수 이상이라 이어서 학습하지 않습니다.")
            return []
        shutil.copyfile(src / f"chkpnt{last}.pth", dest / f"chkpnt{last}.pth")

        def partial(doc):
            doc["training_partial"] = {
                "path": str(dest.relative_to(root)), "checkpoint": last, "iterations": 30000,
                "fingerprint": {"masks": {n: m["sha256"] for n, m in doc["masks"].items()}, "scene": doc["scene"],
                                "iterations": 30000, "resolution": -1}, "time": __import__("studio.store", fromlist=["now"]).now()}

        store.update(pid, partial)
        used.append(f"학습 저장 지점 {last:,}회 (이어서 학습 가능)")
    return used


def _import_mesh(pid, path, iterations):
    """Validate a mesh file, keep the original bytes and make the colour preview."""
    import uuid
    from studio.engines import provider

    root = store.path(pid)
    work = root / "mesh-import" / str(uuid.uuid4())
    work.mkdir(parents=True)
    if path.suffix.lower() == ".ply":
        shutil.copyfile(path, work / "fuse_post.ply")
    else:
        import trimesh
        import numpy as np
        from studio.mesh import glb_colors, linear_to_srgb, check_glb_resources

        check_glb_resources(path)
        mesh = trimesh.load(path, force="mesh", process=False)
        colors = glb_colors(path)
        if colors is not None:
            mesh.visual.vertex_colors = np.column_stack([
                np.rint(np.clip(linear_to_srgb(colors), 0, 1) * 255).astype(np.uint8), np.full(len(colors), 255, np.uint8)])
        mesh.export(work / "fuse_post.ply")
    report = provider("export").validate_and_preview(work / "fuse_post.ply", work)

    def finish(doc):
        doc["mesh"] = {**report, "path": str(work.relative_to(root)), "source_name": path.name,
                       **({"iterations": iterations} if iterations else {})}
        doc["stages"]["mesh"] = "completed"
        doc.setdefault("stage_provenance", {})["mesh"] = {"stage_source": "imported", "stage_state": "verified",
                                                         "skip_reason": "existing_valid_output"}

    store.update(pid, finish)


@app.get("/api/projects/{project_id}/assets")
def project_assets(project_id: str):
    """Files the Project Explorer shows beyond the project document (checkpoints, model files)."""
    import re

    p = store.get(project_id)
    root = store.path(project_id)
    runs = set()
    for key in ("training", "training_partial"):
        if p.get(key):
            runs.add(p[key]["path"])
    checkpoints = []
    for run in sorted(runs):
        for f in sorted((root / run).glob("chkpnt*.pth")):
            m = re.fullmatch(r"chkpnt(\d+)\.pth", f.name)
            if m:
                checkpoints.append({"name": f.name, "iteration": int(m[1]), "bytes": f.stat().st_size,
                                    "path": str(f.relative_to(root)),
                                    "resumable": bool(p.get("training_partial") and p["training_partial"]["path"] == run
                                                      and p["training_partial"]["checkpoint"] == int(m[1]))})
    mesh_files = []
    if p.get("mesh"):
        d = root / p["mesh"]["path"]
        for f in sorted(d.rglob("*")):
            if f.is_file() and f.suffix.lower() in {".ply", ".glb"}:
                mesh_files.append({"name": f.relative_to(d).as_posix(), "bytes": f.stat().st_size, "path": str(f.relative_to(root))})
    return {"checkpoints": checkpoints, "mesh_files": mesh_files, "project_path": str(root)}


class LiveStart(Strict):
    gpu: int = 0
    iteration: int | None = None


class LiveFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    view: list[float] = Field(min_length=16, max_length=16)
    fovy: float = Field(gt=0.05, lt=3.0)
    width: int = Field(ge=16, le=4096)
    height: int = Field(ge=16, le=4096)
    znear: float = Field(default=0.01, gt=0)
    zfar: float = Field(default=1000.0, gt=0)
    mode: str = Field(default="rgb", pattern="^[a-z]{2,16}$")
    encoding: str = Field(default="jpeg", pattern="^(jpeg|png)$")
    quality: int = Field(default=88, ge=50, le=95)
    scaling: float = Field(default=1.0, ge=0.01, le=1.0)

    @model_validator(mode="after")
    def valid_clip_planes(self):
        if self.zfar <= self.znear:
            raise ValueError("카메라 원거리 절단면은 근거리 절단면보다 커야 합니다.")
        return self


def _live_model(project_id, iteration=None):
    from studio.engines import provider

    p = store.get(project_id)
    return p, provider("rendering").locate_model(store.path(project_id), p, iteration)


@app.get("/api/projects/{project_id}/live-render")
def live_render_info(project_id: str, iteration: int | None = None):
    """What the live Gaussian viewport can show for this project (no GPU work)."""
    from studio import live_render
    from studio.engines import provider

    try:
        p, model = _live_model(project_id, iteration)
    except (FileNotFoundError, ValueError) as exc:
        return {"available": False, "reason": str(exc)}
    session = live_render.session_for(project_id)
    ext = provider("rendering").info()
    return {
        "available": True,
        "model": {k: model[k] for k in ("iterations", "iteration", "gaussians", "ply_bytes", "cameras", "target")},
        "training_running": bool((store.active(project_id) or {}).get("stage") in ("train", "mesh")),
        "session": session.status() if session else None,
        "external_viewer": bool(ext.get("external_viewer")) and not ext.get("external_viewer_missing_libraries"),
    }


@app.post("/api/projects/{project_id}/live-render/start")
def live_render_start(project_id: str, body: LiveStart):
    from studio import live_render

    active = store.active(project_id)
    if active and active.get("stage") in ("colmap", "train", "mesh", "sam"):
        raise HTTPException(409, "GPU 작업이 실행 중입니다. 작업이 끝난 뒤 실시간 렌더를 사용할 수 있습니다.")
    gpu = next((g for g in health()["gpus"] if g["index"] == body.gpu), None)
    if gpu is None:
        raise HTTPException(409, "사용할 수 있는 NVIDIA GPU가 없습니다.")
    try:
        _, model = _live_model(project_id, body.iteration)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc))
    try:
        status = live_render.start(gpu.get("uuid", str(body.gpu)), project_id, model,
                                   store.path(project_id) / "logs" / "live-render.log")
    except live_render.LiveRenderError as exc:
        raise HTTPException(409 if exc.state == "busy" else 503, str(exc), headers={"X-Live-State": exc.state})
    return status


@app.post("/api/projects/{project_id}/live-render/frame")
def live_render_frame(project_id: str, body: LiveFrame):
    from fastapi.responses import Response
    from studio import live_render

    try:
        data, stats = live_render.frame(project_id, body.model_dump(), body.encoding)
    except live_render.LiveRenderError as exc:
        raise HTTPException(503, str(exc), headers={"X-Live-State": exc.state})
    headers = {f"X-Render-{k.replace('_', '-')}": str(v) for k, v in stats.items() if v is not None}
    return Response(data, media_type="image/png" if body.encoding == "png" else "image/jpeg",
                    headers={**headers, "Cache-Control": "no-store"})


@app.post("/api/projects/{project_id}/live-render/stop")
def live_render_stop(project_id: str):
    from studio import live_render

    return {"stopped": live_render.release(project_id=project_id)}


@app.post("/api/projects/{project_id}/live-render/external")
def live_render_external(project_id: str):
    """Advanced: attach the bundled SIBR remote viewer window to the running renderer."""
    from studio import live_render

    session = live_render.session_for(project_id)
    if session is None:
        raise HTTPException(409, "먼저 실시간 렌더를 시작하세요.")
    try:
        session.open_external()
    except live_render.LiveRenderError as exc:
        raise HTTPException(409, str(exc))
    return session.status()


@app.get("/api/projects/{project_id}/sparse-points")
def sparse_points(project_id: str, limit: int = 150000):
    """Sparse 3D points (xyz+rgb) and camera poses of the selected reconstruction for the viewer."""
    import base64
    import numpy as np
    from studio.colmap import loader, read_model

    p = store.get(project_id)
    if not p.get("scene"):
        raise HTTPException(404, "카메라 정합 결과가 없습니다.")
    model = store.path(project_id) / p["scene"] / "sparse/0"
    reader = loader()
    xyz, rgb, _ = reader.read_points3D_binary(str(model / "points3D.bin"))
    if len(xyz) > limit:
        idx = np.random.default_rng(0).choice(len(xyz), limit, replace=False)
        xyz, rgb = xyz[idx], rgb[idx]
    _, poses = read_model(model)
    cams = []
    for pose in sorted(poses.values(), key=lambda q: q.name):
        R = reader.qvec2rotmat(pose.qvec)
        cams.append({"name": pose.name, "center": (-R.T @ pose.tvec).tolist(), "rotation": R.T.tolist()})
    enc = lambda a, t: base64.b64encode(np.ascontiguousarray(a, dtype=t).tobytes()).decode()  # noqa: E731
    return {"count": int(len(xyz)), "xyz": enc(xyz, np.float32), "rgb": enc(rgb, np.uint8), "cameras": cams}


_HELP_DOCS = {"quickstart": "docs/QUICKSTART.md", "guide": "docs/USER_GUIDE.md", "troubleshooting": "docs/TROUBLESHOOTING.md", "shortcuts": "docs/SHORTCUTS.md"}


@app.get("/api/help/{name}")
def help_document(name: str):
    """In-app help (Markdown shipped with the application; whitelisted names only)."""
    if name not in _HELP_DOCS:
        raise HTTPException(404, "도움말을 찾을 수 없습니다.")
    path = ROOT / _HELP_DOCS[name]
    return {"name": name, "markdown": path.read_text() if path.is_file() else "도움말 파일이 설치되지 않았습니다."}


@app.get("/api/about")
def about():
    from studio.config import VERSION
    from studio.engines import read_build_info, colmap_binary

    build = None
    try:
        build = read_build_info(colmap_binary()[0])
    except RuntimeError:
        pass
    commit = None
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip() or None
    except OSError:
        pass
    manifest = ROOT / "release-manifest.json"
    return {"app": "M4ML Studio", "version": VERSION, "source_commit": commit,
            "release": json.loads(manifest.read_text()).get("version") if manifest.is_file() else None,
            "camera_engine_build": build and {k: build.get(k) for k in ("tag", "commit", "profile", "cuda_toolkit")},
            "desktop": DESKTOP, "data": str(store.root), "install_root": str(ROOT)}


@app.get("/api/gpu-monitor")
def gpu_monitor():
    """GPU load plus which M4ML Studio processes currently hold GPU memory."""
    fields = "index,name,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw,power.limit"
    gpus, apps = [], []
    try:
        out = subprocess.run(["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, check=True).stdout
        for line in out.splitlines():
            v = [x.strip() for x in line.split(",")]
            num = lambda x: float(x) if x.replace(".", "", 1).isdigit() else None  # noqa: E731
            gpus.append({"index": int(v[0]), "name": v[1], "total_mb": num(v[2]), "used_mb": num(v[3]),
                         "util": num(v[4]), "temp": num(v[5]), "power": num(v[6]), "power_limit": num(v[7])})
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, check=True).stdout
        for line in out.splitlines():
            try:
                pid, used = (int(x) for x in line.split(","))
                cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            except (ValueError, OSError):
                continue
            role = ("객체 선택 세션" if "sam31_session" in cmd else "카메라 정합" if "colmap" in cmd
                    else "3D 재구성" if "train.py" in cmd else "3D 모델 생성" if "render.py" in cmd
                    else "마스크 생성" if "studio.sam31" in cmd else None)
            if role:
                apps.append({"pid": pid, "used_mb": used, "role": role})
    except (OSError, subprocess.SubprocessError):
        pass
    return {"gpus": gpus, "apps": apps, "time": time.time()}


@app.post("/api/projects/{project_id}/duplicate")
def duplicate_project(project_id: str, body: Name):
    """다른 이름으로 저장: copy the whole project (files + document) under a new id."""
    import uuid

    src = store.get(project_id)
    if store.active(project_id):
        raise ValueError("작업이 끝난 뒤 다른 이름으로 저장하세요.")
    new_id = str(uuid.uuid4())
    source, target = store.path(project_id), store.path(new_id)
    if shutil.disk_usage(store.root).free < sum(f.stat().st_size for f in source.rglob("*") if f.is_file()) + 1024**3:
        raise ValueError("저장 공간이 부족합니다.")
    shutil.copytree(source, target, symlinks=True)
    doc = json.loads(json.dumps(src))
    doc.update(id=new_id, name=body.name.strip(), created=__import__("studio.store", fromlist=["now"]).now(), duplicated_from=project_id)
    doc.pop("live_prompt", None)
    with store.db() as db:
        db.execute("INSERT INTO projects VALUES (?,?)", (new_id, json.dumps(doc, ensure_ascii=False)))
    from studio.doctor import atomic_json

    atomic_json(target / "manifest.json", doc)
    return doc


@app.delete("/api/projects/{project_id}/images/{name}")
def remove_image(project_id: str, name: str):
    """Remove a photo from the import list (only before camera registration starts)."""
    with editable(project_id) as (p, root):
        if p["stages"]["import"] == "completed":
            raise ValueError("카메라 정합을 시작한 뒤에는 사진을 제거할 수 없습니다. 새 프로젝트를 만드세요.")
        if not any(i["name"] == name for i in p["images"]):
            raise ValueError("사진을 찾을 수 없습니다.")
        # files are kept (raw snapshot); only the import list changes

        def drop(doc):
            images = [i for i in doc["images"] if i["name"] != name]
            # An exact duplicate of the removed photo becomes the usable copy; the rest point at it.
            heir = next((i for i in images if i.get("duplicate_of") == name), None)
            for i in images:
                if i.get("duplicate_of") == name:
                    i["duplicate_of"] = None if i is heir else heir["name"]
                if i.get("near_duplicate_of") == name:
                    i["near_duplicate_of"] = None
            doc["images"] = images

        return store.update(project_id, drop)


@app.get("/api/projects/{project_id}/preflight")
def training_preflight(project_id: str):
    return preflight(store.get(project_id), store.path(project_id))


@app.post("/api/projects/{project_id}/jobs/{stage}")
def start_job(project_id: str, stage: str, body: Job):
    with editable(project_id) as (p, root):
        request = body.model_dump()
        if stage == "preview" and body.session_id:
            from studio.live_prompt import matches

            if (
                not matches(p, request)
                or p.get("live_prompt", {}).get("status") != "pending"
            ):
                raise HTTPException(409, "취소되었거나 이전 클릭의 추론 요청입니다.")
        if stage == "colmap":
            if p["stages"]["import"] != "completed":
                raise ValueError("사진 불러오기를 먼저 완료하세요.")
            if body.component is not None and body.component not in p.get(
                "colmap_report", {}
            ).get("components", {}):
                raise ValueError("등록된 재구성 그룹을 선택하세요.")
            if body.component is None:
                from studio.engines import provider

                camera = provider("camera")
                if body.cpu_fallback:
                    if not body.confirmed:
                        raise ValueError("GPU 없이 CPU로 카메라 정합을 실행하려면 확인이 필요합니다. 시간이 오래 걸릴 수 있습니다.")
                    request["cpu_fallback_confirmed"] = True
                    camera.binary()  # any working engine
                else:
                    devices = health()["gpus"]
                    gpu = next((g for g in devices if g["index"] == body.gpu), None)
                    if gpu is None:
                        raise ValueError("GPU를 찾을 수 없어 가속 카메라 정합을 실행할 수 없습니다. CPU 실행을 선택할 수 있습니다.")
                    try:
                        camera.binary(require_cuda=True)
                    except RuntimeError as exc:
                        raise ValueError(str(exc)) from exc
                    request["gpu_uuid"] = gpu.get("uuid", str(body.gpu))
        elif stage in {"preview", "sam", "train", "mesh"}:
            device_health = health()
            runtime = device_health.get("runtime_status")
            if runtime and not (runtime.get("available") and runtime.get("anchor_ok")):
                raise ValueError(
                    "GPU 처리 런타임이 설치되지 않았거나 호환되지 않습니다. 설정 › 처리 장치에서 진단 결과를 확인하세요."
                )
            devices = device_health["gpus"]
            gpu = next((g for g in devices if g["index"] == body.gpu), None)
            if gpu is None:
                raise ValueError("선택한 NVIDIA GPU를 사용할 수 없습니다.")
            request["gpu_uuid"] = gpu.get("uuid", str(body.gpu))
            if gpu["free_mb"] < 2048:
                raise ValueError(
                    "GPU 여유 메모리가 2GB보다 작습니다. 다른 GPU 작업을 종료하세요."
                )
            if not p.get("scene") or p["stages"]["colmap"] != "completed":
                raise ValueError("카메라 등록과 왜곡 보정을 먼저 완료하세요.")
            if stage in {"preview", "sam"}:
                names = validate_scene(root / p["scene"])
                if (
                    body.reference not in names
                    or not body.points
                    or len(body.points) != len(body.labels)
                    or 1 not in body.labels
                ):
                    raise ValueError("등록 사진에서 대상 영역을 선택하세요.")
                with Image.open(root / p["scene"] / "images" / body.reference) as im:
                    w, h = im.size
                import math

                if any(
                    len(point) != 2
                    or not all(math.isfinite(v) for v in point)
                    or not (0 <= point[0] < w and 0 <= point[1] < h)
                    for point in body.points
                ) or any(l not in [0, 1] for l in body.labels):
                    raise ValueError("클릭 좌표 또는 종류가 유효하지 않습니다.")
                if not checkpoint().is_file():
                    raise ValueError("객체 선택 모델 파일을 찾을 수 없습니다. 설정 › 고급 정보에서 경로를 확인하세요.")
                request["checkpoint"] = str(checkpoint())
                if stage == "sam":
                    if body.radius is not None and not p["masks"]:
                        raise ValueError(
                            "전체 마스크를 먼저 생성한 뒤 주변 미검토 사진을 다시 전파할 수 있습니다."
                        )
                    expected = {
                        k: request[k] for k in ("reference", "points", "labels")
                    }
                    if (
                        not body.confirmed
                        or p.get("preview", {}).get("request") != expected
                        or p["preview"]["revision"] != p["revision"]
                    ):
                        raise ValueError(
                            "현재 클릭으로 생성한 미리보기를 먼저 확인하고 전파를 승인하세요."
                        )
            elif stage == "train":
                if body.resume:
                    partial = p.get("training_partial")
                    if not partial:
                        raise ValueError("이어서 학습할 저장 지점이 없습니다.")
                    request["iterations"] = partial["iterations"]
                if body.resolution == 0:
                    raise ValueError("사진 해상도가 유효하지 않습니다.")
                check = preflight(p, root)
                if (
                    not body.confirmed
                    or not check["valid"]
                    or p["stages"]["review"] != "completed"
                ):
                    raise ValueError(
                        "마스크를 검증하고 학습 시작을 명시적으로 승인하세요."
                    )
                if check["disk_free"] < 3 * 1024**3:
                    raise ValueError(
                        "학습에 필요한 저장 공간이 부족합니다. 최소 3GB를 확보하세요."
                    )
            elif stage == "mesh" and p["stages"]["train"] != "completed":
                raise ValueError("학습이 완료된 결과가 필요합니다.")
        else:
            raise ValueError("지원하지 않는 작업입니다.")
        if stage != "preview" and request.get("gpu_uuid"):
            # A long GPU job takes the device: close the interactive selection session.
            from studio import segmentation_session

            segmentation_session.release(request["gpu_uuid"])
            from studio import live_render

            live_render.release(request["gpu_uuid"])
        return {"job_id": launch(store, project_id, stage, request)}


class PromptSession(Strict):
    reference: str
    session_id: str = Field(min_length=1, max_length=64)


@app.post("/api/projects/{project_id}/prompt-session")
def prompt_session(project_id: str, body: PromptSession):
    p = store.get(project_id)
    if not p.get("scene") or body.reference not in registered_names(p, store.path(project_id)):
        raise ValueError("등록된 사진을 선택하세요.")
    active = store.active(project_id)
    if active and active["stage"] != "preview":
        raise HTTPException(409, "다른 작업이 끝난 뒤 마스크를 편집하세요.")
    saved = p.get("live_prompt", {})
    if saved.get("reference") != body.reference or "points" not in saved:
        saved = p.get("prompt", {})
    points = saved.get("points", []) if saved.get("reference") == body.reference else []
    labels = saved.get("labels", []) if saved.get("reference") == body.reference else []
    return store.update(
        project_id,
        lambda doc: doc.update(
            live_prompt={
                **body.model_dump(),
                "prompt_revision": 0,
                "status": "idle",
                "points": points,
                "labels": labels,
            }
        ),
    )


@app.post("/api/projects/{project_id}/prompt")
def queue_prompt(project_id: str, body: Job):
    from studio.live_prompt import schedule, matches

    p = store.get(project_id)
    active = store.active(project_id)
    if active and active["stage"] != "preview":
        raise HTTPException(409, "GPU 작업이 끝난 뒤 클릭을 다시 시도하세요.")
    if not body.session_id or body.prompt_revision is None:
        raise ValueError("추론 세션과 변경 번호가 필요합니다.")
    previous = p.get("live_prompt", {})
    if (
        previous.get("session_id") != body.session_id
        or previous.get("reference") != body.reference
    ):
        raise HTTPException(409, "이전 사진의 추론 요청은 적용하지 않았습니다.")
    if body.prompt_revision <= previous.get("prompt_revision", 0):
        return {"accepted": False, "revision": previous.get("prompt_revision")}
    # Persist the exact latest input even if GPU execution subsequently fails.
    if len(body.points) != len(body.labels) or any(
        v not in [0, 1] for v in body.labels
    ):
        raise ValueError("클릭 점과 라벨을 확인하세요.")
    import math

    with Image.open(
        store.path(project_id) / p["scene"] / "images" / body.reference
    ) as image:
        w, h = image.size
    if any(
        len(point) != 2
        or not all(math.isfinite(v) for v in point)
        or not (0 <= point[0] < w and 0 <= point[1] < h)
        for point in body.points
    ):
        raise ValueError("클릭 좌표가 유효하지 않습니다. 사진 안의 위치를 선택하세요.")
    request = {
        **body.model_dump(),
        "status": "pending" if 1 in body.labels else "empty",
    }

    def update(doc):
        current = doc.get("live_prompt", {})
        if current.get(
            "session_id"
        ) != body.session_id or body.prompt_revision <= current.get(
            "prompt_revision", 0
        ):
            return
        doc["live_prompt"] = request
        if request["status"] == "empty":
            doc.pop("preview", None)

    store.update(project_id, update)
    if request["status"] == "pending":
        schedule(store, project_id, prepare_live_prompt)
    return {
        "accepted": True,
        "project_id": project_id,
        "frame_id": body.reference,
        "session_id": body.session_id,
        "revision": body.prompt_revision,
    }


class Warmup(Strict):
    gpu: int = Field(default=0, ge=0, le=31)


_warming = set()


@app.post("/api/projects/{project_id}/selection/warmup")
def selection_warmup(project_id: str, body: Warmup):
    """Start loading the object-selection model in the background (no GPU job running)."""
    import threading
    from studio import segmentation_session

    p = store.get(project_id)
    if store.active(project_id) or not p.get("scene"):
        return {"state": "skipped"}
    gpu = next((g for g in health()["gpus"] if g["index"] == body.gpu), None)
    if gpu is None or not checkpoint().is_file():
        return {"state": "unavailable"}
    device = gpu.get("uuid", str(body.gpu))
    if device in segmentation_session.status():
        return {"state": "ready"}
    if device not in _warming:
        _warming.add(device)

        def warm():
            try:
                segmentation_session.get(device, store.path(project_id) / "logs" / "live-selection.log")
            except Exception:
                pass  # the first click reports the real error to the user
            finally:
                _warming.discard(device)

        threading.Thread(target=warm, daemon=True).start()
    return {"state": "loading"}


def registered_names(p, root):
    """Registered images of the selected reconstruction (fast path: stored report)."""
    report = p.get("colmap_report") or {}
    names = {i["name"] for i in report.get("images", []) if i.get("registered")}
    return names or (validate_scene(root / p["scene"]) if p.get("scene") else set())


_gpu_cache = {"time": 0.0, "gpus": []}


def cached_gpus(max_age=10.0):
    """GPU list for hot paths (live clicks); refreshed at most every ``max_age`` seconds."""
    if time.monotonic() - _gpu_cache["time"] > max_age:
        _gpu_cache.update(time=time.monotonic(), gpus=health()["gpus"])
    return _gpu_cache["gpus"]


def prepare_live_prompt(project_id, request):
    """Validate one interactive click revision; return (image path, GPU device id).

    Hot path: no full scene validation (that decodes every image). The registered set was
    validated when camera registration/import completed and is re-audited at startup."""
    p = store.get(project_id)
    root = store.path(project_id)
    if not p.get("scene") or p["stages"]["colmap"] != "completed":
        raise ValueError("카메라 정합을 먼저 완료하세요.")
    registered = registered_names(p, root)
    image = root / p["scene"] / "images" / request["reference"]
    if request["reference"] not in registered or not image.is_file() or Path(request["reference"]).name != request["reference"]:
        raise ValueError("등록된 사진에서만 객체를 선택할 수 있습니다.")
    gpu = next((g for g in cached_gpus() if g["index"] == request.get("gpu", 0)), None)
    if gpu is None:
        raise ValueError("선택한 GPU를 사용할 수 없습니다. 설정 › 처리 장치를 확인하세요.")
    if not checkpoint().is_file():
        raise ValueError("객체 선택 모델 파일을 찾을 수 없습니다. 설정 › 고급 정보에서 경로를 확인하세요.")
    return image, gpu.get("uuid", str(request.get("gpu", 0)))


@app.post("/api/projects/{project_id}/cancel")
def cancel(project_id: str):
    if store.get(project_id).get("live_prompt", {}).get("status") == "pending":
        store.update(
            project_id, lambda doc: doc["live_prompt"].update(status="cancelled")
        )
    job = store.active(project_id)
    if job and job["pid"]:
        store.job_update(
            job["id"], cancel_requested=1, message="작업을 중지하고 있습니다."
        )
        try:
            os.kill(job["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
    return {"message": "중지 요청을 보냈습니다. 종료 상태와 로그를 확인하세요."}


def review_state(doc):
    values = list(doc["masks"].values())
    doc["stages"]["review"] = (
        "completed"
        if values
        and all(
            m.get("valid") and m["status"] in {"approved", "manual", "skipped"}
            for m in values
        )
        else "review_required"
    )


@app.put("/api/projects/{project_id}/masks/{name}")
def save_mask(project_id: str, name: str, body: Mask):
    with editable(project_id) as (p, root):
        if p.get("live_prompt", {}).get("status") == "pending":
            raise HTTPException(409, "최신 클릭 추론이 끝난 뒤 저장·승인하세요.")
        if name not in p["masks"]:
            raise ValueError("생성된 마스크가 있는 등록 사진을 선택하세요.")
        item = dict(p["masks"][name])
        path = root / item["path"]
        with Image.open(root / p["scene"] / "images" / name) as image:
            size = image.size
        if body.png:
            from io import BytesIO

            try:
                data = base64.b64decode(body.png, validate=True)
            except ValueError as exc:
                raise ValueError("마스크 파일을 읽을 수 없습니다.") from exc
            # Decode/validate before persisting anything over the previous mask.
            with Image.open(BytesIO(data)) as image:
                import numpy as np

                if image.size != size:
                    raise ValueError("마스크 크기가 사진과 다릅니다.")
                a = np.asarray(image)
                if image.mode in {"RGB", "RGBA"}:
                    if (
                        not np.array_equal(a[:, :, 0], a[:, :, 1])
                        or not np.array_equal(a[:, :, 0], a[:, :, 2])
                        or (image.mode == "RGBA" and not np.all(a[:, :, 3] == 255))
                    ):
                        raise ValueError("불투명한 흑백 이진 마스크가 필요합니다.")
                    image = image.convert("L")
                    a = np.asarray(image)
                if (
                    image.mode != "L"
                    or a.dtype != np.uint8
                    or not np.isin(a, [0, 255]).all()
                    or not np.any(a)
                ):
                    raise ValueError("사진 크기와 같은 흑백 이진 마스크가 필요합니다.")
                encoded = BytesIO()
                image.save(encoded, format="PNG")
                data = encoded.getvalue()
            path = root / "masks/manual" / (Path(name).stem + ".png")
            atomic_bytes(path, data)
            item["path"] = str(path.relative_to(root))
        stats = validate_mask(path, size)
        item.pop("error", None)
        item.update(
            stats,
            valid=True,
            status=(
                "manual"
                if body.approve and (body.png or item.get("status") == "manual")
                else "approved" if body.approve else "generated"
            ),
        )

        def finish(doc):
            doc["masks"][name] = item
            if doc.get("preview", {}).get("reference") == name:
                doc.pop("preview", None)
            invalidate(doc, "review")
            review_state(doc)

        return store.update(project_id, finish)


@app.post("/api/projects/{project_id}/skip-review")
def skip(project_id: str, body: Confirm):
    if not body.confirmed:
        raise ValueError("남은 마스크의 수동 검토 생략을 확인하세요.")
    with editable(project_id) as (p, root):
        names = validate_scene(root / p["scene"])
        updates = {}
        for name in names:
            item = dict(p["masks"].get(name, {}))
            if not item.get("valid"):
                raise ValueError(f"유효한 마스크가 없습니다: {name}")
            with Image.open(root / p["scene"] / "images" / name) as image:
                stats = validate_mask(root / item["path"], image.size)
            if stats["sha256"] != item["sha256"]:
                raise ValueError("마스크 파일이 변경되었습니다.")
            if item["status"] == "generated":
                item["status"] = "skipped"
            updates[name] = item

        def finish(doc):
            doc["masks"].update(updates)
            doc["review_skip"] = {"confirmed": True, "time": time.time()}
            invalidate(doc, "review")
            review_state(doc)

        return store.update(project_id, finish)


@app.get("/api/projects/{project_id}/files/{path:path}")
def artifact(project_id: str, path: str):
    root = store.path(project_id)
    store.get(project_id)
    file = (root / path).resolve()
    if not file.is_relative_to(root) or file.suffix.lower() not in {
        ".png",
        ".jpg",
        ".jpeg",
        ".ply",
        ".glb",
        ".json",
        ".log",
    }:
        raise HTTPException(403, "허용된 프로젝트 결과 파일만 열 수 있습니다.")
    if not file.is_file():
        raise FileNotFoundError("결과 파일을 찾을 수 없습니다.")
    return FileResponse(file)


@app.get("/api/projects/{project_id}/events")
async def events(project_id: str, request: Request):
    store.get(project_id)

    async def stream():
        import asyncio

        cursor = 0
        while not await request.is_disconnected():
            with store.db() as db:
                rows = db.execute(
                    "SELECT id,payload FROM events WHERE project_id=? AND id>? ORDER BY id LIMIT 100",
                    (project_id, cursor),
                ).fetchall()
            for row in rows:
                cursor = row[0]
                yield f"id: {cursor}\ndata: {row[1]}\n\n"
            yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/projects/{project_id}/logs/{job_id}")
def job_log(project_id: str, job_id: str):
    job = store.job(job_id)
    if job["project_id"] != project_id:
        raise HTTPException(403, "다른 프로젝트의 로그입니다.")
    root = store.path(project_id)
    candidates = [
        root / "logs" / (job_id + ".log"),
        root / "runs" / job_id / "colmap/colmap.log",
        root / "logs" / (job_id + "-worker.log"),
    ]
    for path in candidates:
        if path.is_file():
            with path.open("rb") as stream:
                stream.seek(max(0, path.stat().st_size - 16000))
                return {"text": stream.read().decode("utf-8", errors="replace")}
    return {"text": "작업을 준비하고 있습니다."}


_metric_cache = {}


@app.get("/api/projects/{project_id}/training-metrics/{job_id}")
def training_metrics(project_id: str, job_id: str):
    """Full training curve parsed server-side from the real trainer logs (downsampled).

    A resumed run continues the curve of the run it resumed from (absolute iterations)."""
    job = store.job(job_id)
    if job["project_id"] != project_id or job["stage"] != "train":
        raise HTTPException(404, "학습 작업이 아닙니다.")
    rows, status = _training_rows(project_id, job_id, depth=0)
    step = max(1, len(rows) // 800)
    sampled = rows[::step] + ([rows[-1]] if rows and (len(rows) - 1) % step else [])
    return {"samples": sampled, "status": status}


_metric_cache = {}
_PROGRESS = __import__("re").compile(
    r"(\d+)/(\d+)\s*\[([\d:]+)<([\d:?]+),\s*([\d.]+)it/s,\s*Loss=([\d.eE+-]+)"
    r"(?:,\s*distort=([\d.eE+-]+))?(?:,\s*normal=([\d.eE+-]+))?(?:,\s*Points=(\d+))?"
)


def _training_rows(project_id, job_id, depth):
    path = store.path(project_id) / "logs" / (job_id + ".log")
    if not path.is_file() or depth > 8:
        return [], {}
    key = (str(path), path.stat().st_size, path.stat().st_mtime)
    cached = _metric_cache.get(job_id)
    if cached and cached[0] == key:
        rows, status, resume = cached[1]
    else:
        samples, status, resume = {}, {}, None
        with path.open("r", errors="replace") as stream:
            for chunk in stream:
                if chunk.startswith('{"m4ml_resume"'):
                    try:
                        resume = json.loads(chunk)["m4ml_resume"]
                    except ValueError:
                        pass
                    continue
                for m in _PROGRESS.finditer(chunk):
                    it = int(m[1])
                    samples[it] = [it, int(m[2]), float(m[6]), float(m[7]) if m[7] else None,
                                   float(m[8]) if m[8] else None, int(m[9]) if m[9] else None]
                    status = {"elapsed": m[3], "remaining": m[4], "rate": float(m[5])}
        rows = [samples[k] for k in sorted(samples)]
        _metric_cache[job_id] = (key, (rows, status, resume))
    if resume:
        offset, total = int(resume["offset"]), int(resume["total"])
        rows = [[r[0] + offset, total, *r[2:]] for r in rows]
        previous, _ = _training_rows(project_id, resume.get("previous_job", ""), depth + 1)
        rows = [r for r in previous if r[0] <= offset] + rows
    return rows, status


if (ROOT / "frontend/dist").is_dir():
    app.mount(
        "/", StaticFiles(directory=ROOT / "frontend/dist", html=True), name="frontend"
    )
