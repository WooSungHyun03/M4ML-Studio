"""Server-side upload limits (draft values from the plan; T04 measurements may change them).

Usage is measured on disk (photos, masks, training output, checkpoints, meshes, logs), not
counted in the browser. Full reservation accounting and deletion come with T11.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

MAX_PHOTOS_PER_PROJECT = 100
SESSION_BYTES = 10 * 2**30
MIN_FREE_BYTES = int(float(os.environ.get("STUDIO_WEB_MIN_FREE_GB", "100")) * 2**30)


def directory_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                st = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            total += st.st_size
    return total


def admit_photo(config, session_dir: Path, project: dict, size: int) -> str | None:
    """Return a refusal message (Korean) or None when the photo may be stored."""
    if len(project.get("images", [])) >= MAX_PHOTOS_PER_PROJECT:
        return f"프로젝트당 사진은 {MAX_PHOTOS_PER_PROJECT}장까지 올릴 수 있습니다."
    if directory_bytes(session_dir) + size > SESSION_BYTES:
        return "작업 공간 저장 용량(10GB)을 모두 사용했습니다. 필요 없는 프로젝트를 삭제하세요."
    if shutil.disk_usage(config.home).free - size < MIN_FREE_BYTES:
        return "서버 저장 공간이 부족해 지금은 사진을 받을 수 없습니다."
    return None


# Work that writes results (camera registration, training, mesh) needs room for its output.
# T04: a 100-photo project grew by about 1.5 GB after import (registration, masks, training,
# mesh); keep a 2 GB margin inside the session quota.
JOB_HEADROOM_BYTES = 2 * 2**30
OUTPUT_TEMPLATES = ("/api/projects/{project_id}/jobs/{stage}", "/api/projects/{project_id}/import-complete")


def admit_job(config, session_dir: Path) -> str | None:
    if directory_bytes(session_dir) + JOB_HEADROOM_BYTES > SESSION_BYTES:
        return "작업 공간 저장 용량(10GB)이 부족해 새 작업을 시작할 수 없습니다. 필요 없는 프로젝트를 삭제하세요."
    if shutil.disk_usage(config.home).free < MIN_FREE_BYTES + JOB_HEADROOM_BYTES:
        return "서버 저장 공간이 부족해 지금은 새 작업을 시작할 수 없습니다."
    return None
