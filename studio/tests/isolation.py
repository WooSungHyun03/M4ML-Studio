"""Import before `studio.api` in any test module.

studio.api creates its Store at import time; without this the test process would open the
desktop user's real data directory (~/.local/share/...). Tests replace api.store with their
own temporary stores, so the import-time store only needs to be harmless and disposable."""

import atexit
import os
import shutil
import tempfile

_root = tempfile.mkdtemp(prefix="m4ml-test-data-")
os.environ["STUDIO_DATA"] = _root
atexit.register(shutil.rmtree, _root, ignore_errors=True)
