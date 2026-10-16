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
from pydantic import BaseModel, Field, ConfigDict
from PIL import Image

from studio.colmap import validate_scene
from studio.dispatch import launch
from studio.doctor import ROOT
from studio.importer import import_image, atomic_bytes, MAX_FILE
from studio.sam31 import validate_mask
from studio.store import Store, invalidate

TOKEN = secrets.token_urlsafe(32)
store = Store()


@asynccontextmanager
async def lifespan(app):
    store.reconcile()
    yield
    for project in store.list():
        active = store.active(project["id"])
        if active and active["pid"]:
            try:
                os.kill(active["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass


app = FastAPI(title="Object-Aware 재구성 스튜디오", lifespan=lifespan)


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


class Job(Strict):
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


class Mask(Strict):
    png: str | None = Field(default=None, max_length=50000000)
    approve: bool = True


class Confirm(Strict):
    confirmed: bool


@app.get("/api/session")
def session():
    return {"token": TOKEN}


@app.get("/api/health")
def health():
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.free,uuid",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        gpus = []
        for line in result.stdout.splitlines():
            i, name, total, free, uuid = [v.strip() for v in line.split(",")]
            gpus.append(
                {
                    "index": int(i),
                    "name": name,
                    "total_mb": int(total),
                    "free_mb": int(free),
                    "uuid": uuid,
                }
            )
        error = None
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        gpus = []
        error = str(exc)
    return {
        "gpus": gpus,
        "gpu_error": error,
        "colmap": shutil.which("colmap") is not None,
        "disk_free": shutil.disk_usage(store.root).free,
        "runtime": str(Path(os.sys.executable)),
        "checkpoint_exists": checkpoint().is_file(),
    }


def checkpoint():
    return Path(
        os.environ.get(
            "STUDIO_SAM_CHECKPOINT", ROOT / "models/sam3.1/sam3.1_multiplex.pt"
        )
    ).resolve()


@app.get("/api/projects")
def projects():
    return store.list()


@app.post("/api/projects")
def create(body: Name):
    return store.create(body.name)


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
        return {
            "job_id": launch(store, project_id, "colmap", {"matching": "exhaustive"})
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


@app.get("/api/projects/{project_id}/preflight")
def training_preflight(project_id: str):
    return preflight(store.get(project_id), store.path(project_id))


@app.post("/api/projects/{project_id}/jobs/{stage}")
def start_job(project_id: str, stage: str, body: Job):
    with editable(project_id) as (p, root):
        request = body.model_dump()
        if stage == "colmap":
            if p["stages"]["import"] != "completed":
                raise ValueError("사진 불러오기를 먼저 완료하세요.")
            if body.component is not None and body.component not in p.get(
                "colmap_report", {}
            ).get("components", {}):
                raise ValueError("등록된 재구성 그룹을 선택하세요.")
        elif stage in {"preview", "sam", "train", "mesh"}:
            devices = health()["gpus"]
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
                    raise ValueError("로컬 SAM 3.1 체크포인트를 찾을 수 없습니다.")
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
        return {"job_id": launch(store, project_id, stage, request)}


@app.post("/api/projects/{project_id}/cancel")
def cancel(project_id: str):
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
                if body.png and body.approve
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


if (ROOT / "frontend/dist").is_dir():
    app.mount(
        "/", StaticFiles(directory=ROOT / "frontend/dist", html=True), name="frontend"
    )
