"""Immutable raw snapshots and EXIF-normalized canonical images; originals untouched."""

from io import BytesIO
from pathlib import Path
import os
import tempfile
import warnings

from PIL import Image, ImageOps, ImageStat
from studio.doctor import sha256

MAX_FILE = 128 * 1024 * 1024
MAX_PIXELS = 50_000_000


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def import_image(root, data, source_name, index, existing):
    if len(data) > MAX_FILE:
        raise ValueError("파일이 128MB를 초과합니다.")
    if len(source_name) > 2048 or not data:
        raise ValueError("파일 이름 또는 내용이 유효하지 않습니다.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(data)) as raw:
            if raw.format not in {"JPEG", "PNG", "TIFF"}:
                raise ValueError("JPG, PNG, TIFF 사진을 선택하세요.")
            if raw.width * raw.height > MAX_PIXELS:
                raise ValueError("사진이 5천만 화소를 초과합니다.")
            exif = raw.getexif()
            orientation = exif.get(274)
            capture = str(exif.get(36867, ""))
            normalized = ImageOps.exif_transpose(raw).convert("RGB")
            normalized.load()
    root = Path(root)
    name = f"{index:06d}.png"
    raw_path = root / "input/snapshots" / f"{index:06d}.original"
    atomic_bytes(raw_path, data)
    digest = sha256(raw_path)
    previous = next((i for i in existing if i["source_sha256"] == digest), None)
    encoded = BytesIO()
    normalized.save(encoded, format="PNG")
    canonical_hash = __import__("hashlib").sha256(encoded.getvalue()).hexdigest()
    previous = previous or next(
        (i for i in existing if i["normalized_sha256"] == canonical_hash), None
    )
    import numpy as np
    import cv2

    small = np.asarray(normalized.convert("L").resize((9, 8)))
    bits = (small[:, 1:] > small[:, :-1]).ravel()
    dhash = sum(int(bit) << i for i, bit in enumerate(bits))
    near = next(
        (
            i
            for i in existing
            if i.get("dhash") is not None
            and (int(i["dhash"], 16) ^ dhash).bit_count() <= 4
        ),
        None,
    )
    quality = normalized.copy()
    quality.thumbnail((512, 512))
    sharpness = float(cv2.Laplacian(np.asarray(quality.convert("L")), cv2.CV_64F).var())
    advisories = []
    if near and not previous:
        advisories.append("비슷한 사진이 있습니다. 촬영 시점의 겹침을 확인하세요.")
    if sharpness < 25:
        advisories.append("사진이 흐리거나 세부 무늬가 적을 수 있습니다.")
    # Duplicates are reported and retained as snapshots but excluded from SfM.
    relative = "input/duplicates/" + name if previous else "input/original/" + name
    atomic_bytes(root / relative, encoded.getvalue())
    thumbnail = normalized.copy()
    thumbnail.thumbnail((240, 180))
    thumb = BytesIO()
    thumbnail.save(thumb, format="JPEG", quality=85)
    atomic_bytes(
        root / "input/thumbnails" / (Path(name).stem + ".jpg"), thumb.getvalue()
    )
    return {
        "name": name,
        "source_name": source_name,
        "source_sha256": digest,
        "normalized_sha256": canonical_hash,
        "path": relative,
        "size": list(normalized.size),
        "capture_time": capture,
        "exif_orientation": orientation,
        "duplicate_of": previous["name"] if previous else None,
        "bytes": len(data),
        "thumbnail": "input/thumbnails/" + Path(name).stem + ".jpg",
        "dhash": f"{dhash:016x}",
        "near_duplicate_of": near["name"] if near and not previous else None,
        "sharpness_advisory_score": sharpness,
        "advisories": advisories,
    }
