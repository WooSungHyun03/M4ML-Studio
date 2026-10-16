"""Durable latest-wins prompt queue for interactive object selection.

Every click is persisted first (``live_prompt`` with a monotonically increasing
``prompt_revision``). One pump thread per project sends ONLY the newest pending
revision to the persistent segmentation session; when a reply arrives it is
published only if it still matches the newest revision — results of superseded
clicks are discarded, never displayed.
"""

import json, shutil, threading, time
from pathlib import Path

from studio.store import now

_pumps = {}
_guard = threading.Lock()
_shutdown = threading.Event()


def stop_all():
    _shutdown.set()


def reset():
    _shutdown.clear()


def matches(doc, request):
    live = doc.get("live_prompt", {})
    return all(
        live.get(key) == request.get(key)
        for key in ("session_id", "prompt_revision", "reference")
    )


def cleanup_previews(root, folder, published_path):
    """Keep the published recovery mask even after many superseded predictions."""
    protected = (root / published_path).resolve() if published_path else None
    for old in sorted(p for p in folder.iterdir() if p.is_dir())[:-3]:
        if protected is not None and protected.is_relative_to(old.resolve()):
            continue
        shutil.rmtree(old, ignore_errors=True)


def run_live(store, project_id, request, prepare):
    """Run one revision through the persistent session and publish if still current."""
    from studio import segmentation_session

    image, device = prepare(project_id, request)
    root = store.path(project_id)
    revision = request["prompt_revision"]
    folder = root / "live" / request["session_id"]
    out = folder / f"{revision:06d}" / (Path(request["reference"]).stem + ".png")
    session = segmentation_session.get(device, root / "logs" / "live-selection.log")
    reply = session.predict(image, request["points"], request["labels"], out)
    if not reply.get("ok"):
        raise ValueError(segmentation_session.failure_description(reply.get("error") or "마스크를 계산하지 못했습니다."))
    published = {}

    def finish(doc):
        if not matches(doc, request) or doc.get("live_prompt", {}).get("status") != "pending":
            return  # a newer click exists: discard this result
        prompt = {k: request[k] for k in ("reference", "points", "labels")}
        doc["live_prompt"].update(status="ready", seconds=reply["result"].get("seconds"))
        doc["prompt"] = prompt
        doc["preview"] = {
            "path": str(out.relative_to(root)),
            "reference": request["reference"],
            "request": prompt,
            "revision": doc["revision"],
            "session_id": request["session_id"],
            "prompt_revision": revision,
            "project_id": project_id,
            "frame_id": request["reference"],
            "area": reply["result"].get("area"),
            "coverage": reply["result"].get("coverage"),
        }
        doc["stages"]["sam"] = "completed" if doc["masks"] else "waiting_for_user"
        published["ok"] = True

    store.update(project_id, finish)
    # Keep only the latest few revision folders of this session (bounded disk use).
    try:
        cleanup_previews(root, folder, store.get(project_id).get("preview", {}).get("path"))
    except OSError:
        pass
    return bool(published)


def schedule(store, project_id, prepare):
    key = (str(store.root), project_id)
    with _guard:
        if key in _pumps and _pumps[key].is_alive():
            return

        def pump():
            try:
                for _ in range(7200):
                    if _shutdown.is_set():
                        return
                    p = store.get(project_id)
                    request = p.get("live_prompt", {})
                    if request.get("status") != "pending":
                        return
                    active = store.active(project_id)
                    if active and active["stage"] != "preview":
                        raise ValueError("다른 작업이 끝난 뒤 클릭을 다시 시도하세요.")
                    try:
                        run_live(store, project_id,
                                 {k: v for k, v in request.items() if k not in ("status", "error", "updated")},
                                 prepare)
                    except Exception as exc:  # noqa: BLE001 — user-facing message

                        def fail(doc):
                            if matches(doc, request) and doc.get("live_prompt", {}).get("status") == "pending":
                                doc["live_prompt"].update(status="failed", error=str(exc))

                        store.update(project_id, fail)
                        return
            finally:
                with _guard:
                    _pumps.pop(key, None)
                try:
                    if not _shutdown.is_set() and store.get(project_id).get("live_prompt", {}).get("status") == "pending":
                        schedule(store, project_id, prepare)
                except (OSError, KeyError):
                    pass

        thread = threading.Thread(target=pump, daemon=True)
        _pumps[key] = thread
        thread.start()
