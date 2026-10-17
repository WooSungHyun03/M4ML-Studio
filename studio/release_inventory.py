"""Evidence for actual archive contents, not a grant of distribution rights."""

import hashlib
import importlib.metadata
import json
from pathlib import Path


def inventory(root):
    root = Path(root)
    catalog = json.loads((root / "licenses/catalog.json").read_text())
    texts = {}
    for entry in catalog:
        path = root / entry["text"]
        if not path.is_file():
            raise ValueError(f"라이선스 원문 누락: {entry['text']}")
        texts[entry["text"]] = hashlib.sha256(path.read_bytes()).hexdigest()
    libraries = []
    record = root / "licenses/colmap-runtime/inventory.json"
    if record.is_file():
        for row in json.loads(record.read_text())["libraries"]:
            binary = root / "runtime/colmap/lib" / row["library"]
            if (
                not binary.is_file()
                or hashlib.sha256(binary.read_bytes()).hexdigest() != row["sha256"]
            ):
                raise ValueError(f"런타임 바이너리 식별 불일치: {row['library']}")
            for name in row["notices"]:
                path = root / "licenses/colmap-runtime" / name
                if not path.is_file():
                    raise ValueError(f"종속 라이선스 누락: {name}")
                texts[path.relative_to(root).as_posix()] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
            libraries.append(row)
    lock = json.loads((root / "frontend/package-lock.json").read_text())
    npm = [
        {
            "name": key.removeprefix("node_modules/"),
            "version": value["version"],
            "license": value.get("license", "See upstream notice"),
            "integrity": value.get("integrity"),
        }
        for key, value in sorted(lock["packages"].items())
        if key and not value.get("dev")
    ]
    python = []
    for dist in sorted(
        importlib.metadata.distributions(), key=lambda d: d.metadata["Name"].lower()
    ):
        python.append(
            {
                "name": dist.metadata["Name"],
                "version": dist.version,
                "license_metadata": (
                    dist.metadata.get("License-Expression")
                    or dist.metadata.get("License")
                    or "See installed package notices"
                )[:512],
            }
        )
    return {
        "schema": 1,
        "scope": "archive files and separate build-runtime package inventory",
        "public_distribution_approved": False,
        "commercial_distribution_approved": False,
        "weights_included": False,
        "components": catalog,
        "license_sha256": texts,
        "bundled_colmap_libraries": libraries,
        "frontend_packages": npm,
        "python_packages_installed_separately_not_archived": python,
        "sources": json.loads((root / "SOURCES.json").read_text()),
        "unresolved": [
            "NC upstream rights for public/commercial scenarios",
            "SuiteSparse corresponding-source, relinking and combined distribution",
            "CUDA exact redistribution conditions and Qt/Chromium compliance workflow",
        ],
    }
