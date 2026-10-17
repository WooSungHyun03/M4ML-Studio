"""CPU test suite for CI (GitHub-hosted runners have no NVIDIA GPU).

Runs every studio/tests module except those that need the GPU research runtime:
  test_sam_compat          - imports the official SAM 3.1 package (vendor/sam3 + torch)
  test_scientific_contract - imports the original Object-Aware training code (torch/CUDA)
Those run on the GPU workstation (`python -m unittest discover -s studio/tests`) and in the
installed-package verification; CI never reports them as passed.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GPU_ONLY = {"test_sam_compat", "test_scientific_contract"}
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "studio/tests"))
loader = unittest.TestLoader()
suite = unittest.TestSuite()
for path in sorted((ROOT / "studio/tests").glob("test_*.py")):
    if path.stem in GPU_ONLY:
        print(f"skip (GPU runtime only): {path.stem}")
        continue
    suite.addTests(loader.loadTestsFromName(path.stem))
result = unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(0 if result.wasSuccessful() and result.testsRun > 0 else 1)
