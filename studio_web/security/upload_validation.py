"""Untrusted photo uploads: check, decode under limits, strip metadata without touching pixels.

`inspect_and_clean` runs in a separate worker process (see `validate_in_worker`), so a
hostile file that makes the decoder slow or huge is bounded by a timeout and the process,
not by the gateway's event loop.

Metadata: JPEG APP1 (EXIF/XMP, including GPS), APP13 (IPTC) and COM segments and PNG
text/EXIF chunks are removed at the byte level; compressed image data is not re-encoded.
A JPEG's EXIF orientation is kept as a minimal EXIF block so the photo still shows upright.
"""

from __future__ import annotations

import concurrent.futures
import multiprocessing
import hashlib
import io
import struct
import warnings

MAX_BYTES = 20 * 2**20
MAX_PIXELS = 50_000_000
MIN_SIDE = 64
WORKER_TIMEOUT = 30


class UploadRejected(ValueError):
    """Message is shown to the user (Korean, no server details)."""


def kind(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    raise UploadRejected("JPEG 또는 PNG 사진만 올릴 수 있습니다.")


def _orientation_exif(orientation: int) -> bytes:
    from PIL import Image

    exif = Image.Exif()
    exif[0x0112] = orientation
    return exif.tobytes()  # starts with b"Exif\x00\x00"


def _keep_segment(marker: int, payload: bytes) -> bool:
    """Keep tables, frame headers, JFIF (APP0), ICC profile (APP2 'ICC_PROFILE') and Adobe
    (APP14). Drop EXIF/XMP (APP1), MPF and FlashPix (other APP2, may embed more images and
    EXIF), IPTC (APP13), all other APPn and comments."""
    if marker == 0xFE:
        return False
    if 0xE0 <= marker <= 0xEF:
        return marker in (0xE0, 0xEE) or (marker == 0xE2 and payload.startswith(b"ICC_PROFILE\x00"))
    return True


def strip_jpeg(data: bytes, orientation: int | None) -> bytes:
    if data[:2] != b"\xff\xd8":
        raise UploadRejected("사진 파일이 손상되었습니다.")
    out = bytearray(b"\xff\xd8")
    if orientation and orientation != 1:
        payload = _orientation_exif(orientation)
        out += b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            raise UploadRejected("사진 파일이 손상되었습니다.")
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker == 0xDA:  # start of scan: the rest is entropy-coded image data
            out += data[i:]
            return bytes(out)
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            out += data[i:i + 2]
            i += 2
            continue
        if i + 4 > len(data):
            raise UploadRejected("사진 파일이 손상되었습니다.")
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        segment = data[i:i + 2 + length]
        if len(segment) != 2 + length or length < 2:
            raise UploadRejected("사진 파일이 손상되었습니다.")
        if _keep_segment(marker, segment[4:]):
            out += segment
        i += 2 + length
    raise UploadRejected("사진 파일이 손상되었습니다.")


PNG_DROP = {b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"tIME"}


def strip_png(data: bytes) -> bytes:
    out, i = bytearray(data[:8]), 8
    while i < len(data):
        if i + 12 > len(data):
            raise UploadRejected("사진 파일이 손상되었습니다.")
        length = struct.unpack(">I", data[i:i + 4])[0]
        chunk_type = data[i + 4:i + 8]
        end = i + 12 + length
        if end > len(data):
            raise UploadRejected("사진 파일이 손상되었습니다.")
        if chunk_type not in PNG_DROP:
            out += data[i:end]
        i = end
        if chunk_type == b"IEND":
            return bytes(out)
    raise UploadRejected("사진 파일이 손상되었습니다.")


def _decode(data: bytes):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(io.BytesIO(data)) as probe:
                fmt, size = probe.format, probe.size
                if size[0] * size[1] > MAX_PIXELS:
                    raise UploadRejected("사진이 5천만 화소를 넘습니다.")
                if min(size) < MIN_SIDE:
                    raise UploadRejected("사진이 너무 작습니다.")
                probe.verify()  # must come right after open (getexif() may read the whole PNG)
            with Image.open(io.BytesIO(data)) as image:
                orientation = image.getexif().get(0x0112)
                image.load()
                pixels = hashlib.sha256(image.tobytes()).hexdigest()
                mode = image.mode
        except UploadRejected:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise UploadRejected("사진이 5천만 화소를 넘습니다.") from None
        except Exception:
            raise UploadRejected("사진을 읽을 수 없습니다. 손상되지 않은 JPEG 또는 PNG를 올리세요.") from None
    return fmt, size, mode, orientation, pixels


def inspect_and_clean(data: bytes) -> tuple[bytes, dict]:
    if not data:
        raise UploadRejected("빈 파일입니다.")
    if len(data) > MAX_BYTES:
        raise UploadRejected("사진 한 장은 20MB 이하만 올릴 수 있습니다.")
    expected = kind(data)
    fmt, size, mode, orientation, pixels = _decode(data)
    if fmt != expected:
        raise UploadRejected("파일 내용과 형식이 다릅니다.")
    clean = strip_jpeg(data, orientation) if fmt == "JPEG" else strip_png(data)
    c_fmt, c_size, c_mode, c_orientation, c_pixels = _decode(clean)
    if (c_fmt, c_size, c_mode, c_pixels) != (fmt, size, mode, pixels):
        raise UploadRejected("사진을 안전하게 처리하지 못했습니다.")
    return clean, {"format": fmt, "width": size[0], "height": size[1], "orientation": c_orientation,
                   "bytes_in": len(data), "bytes_out": len(clean)}


_pool: concurrent.futures.ProcessPoolExecutor | None = None


def validate_in_worker(data: bytes) -> tuple[bytes, dict]:
    """Run inspect_and_clean in a worker process with a hard timeout."""
    global _pool
    if _pool is None:
        # "spawn": fresh interpreters. Forked workers would inherit the gateway's listening
        # socket and keep the port busy (and keep running) after the gateway stops.
        _pool = concurrent.futures.ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn"))
    future = _pool.submit(inspect_and_clean, data)
    try:
        return future.result(timeout=WORKER_TIMEOUT)
    except concurrent.futures.TimeoutError:
        # Kill the stuck worker: shutdown() alone waits for nothing but leaves it running.
        processes = list((getattr(_pool, "_processes", None) or {}).values())
        _pool.shutdown(wait=False, cancel_futures=True)
        for process in processes:
            process.kill()
        _pool = None
        raise UploadRejected("사진을 처리하는 데 너무 오래 걸립니다.") from None
    except concurrent.futures.process.BrokenProcessPool:
        _pool = None
        raise UploadRejected("사진을 처리하지 못했습니다.") from None


def display_name(name: str | None) -> str:
    """Keep the browser's file name only as a label: no directories, no control characters."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(c for c in base if c.isprintable()).strip()
    return base[:120] or "사진"
