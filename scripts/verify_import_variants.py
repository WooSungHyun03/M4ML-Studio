"""Real calibration import checks, without running SfM; mask warp has explicit synthetic-unit scope."""

import json, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.colmap_import import commit_import
from studio.process import run
from studio.doctor import atomic_json

work = Path("evidence/m4ml-import-variants")
work.mkdir(exist_ok=True)
report = {}
# TXT + non-default model id + custom image directory, copied real measured calibration.
root = work / "ascii"
upload = root / "import-upload"
(upload / "sparse/7").mkdir(parents=True, exist_ok=True)
source = Path("evidence/m4ml-fixtures/registered-colmap")
shutil.copytree(source / "images", upload / "custom photos", dirs_exist_ok=True)
run(
    [
        "colmap",
        "model_converter",
        "--input_path",
        str(source / "sparse/0"),
        "--output_path",
        str(upload / "sparse/7"),
        "--output_type",
        "TXT",
    ],
    work / "variants.log",
)
r = commit_import(root, {"sparse": "sparse/7", "images": "custom photos"})
assert (
    r["committed"]
    and len(r["images"]) == 16
    and not r["provenance"]["undistorted_during_import"]
)
report["ascii_custom"] = {
    "status": "PASS",
    "registered": 16,
    "provenance": r["provenance"],
}
# Original distorted source from genuine earlier COLMAP, original raw calibration photos.
root = work / "distorted"
upload = root / "import-upload"
shutil.copytree(
    Path("evidence/colmap-real-1/sparse/0"),
    upload / "distorted/sparse/0",
    dirs_exist_ok=True,
)
shutil.copytree(
    Path("datasets/south-building-sample/images"), upload / "input", dirs_exist_ok=True
)
r = commit_import(root, {})
assert (
    r["committed"]
    and len(r["images"]) == 16
    and r["provenance"]["undistorted_during_import"]
)
report["distorted_only_undistorter"] = {
    "status": "PASS",
    "registered": 16,
    "provenance": r["provenance"],
}
log = "".join(p.read_text() for p in root.rglob("*.log"))
assert (
    "image_undistorter" in log
    and "feature_extractor" not in log
    and "exhaustive_matcher" not in log
)
atomic_json(work / "result.json", report)
print(json.dumps(report, ensure_ascii=False))
