"""Real flock ownership during an interrupted constructor (no CUDA inference claim)."""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from studio import gpu_lock, segmentation_session as sessions


class HandoverTests(unittest.TestCase):
    def test_release_waits_until_cancelled_startup_has_closed_its_gpu(self):
        acquired, proceed, closed, released = [threading.Event() for _ in range(4)]
        errors = []

        class Starting:
            def __init__(self, device, log, idle):
                self.lock = gpu_lock.try_acquire(device)
                acquired.set()
                proceed.wait(5)

            def close(self):
                self.lock.close()
                closed.set()

        def load():
            try:
                sessions.get("handover-test", Path("unused"))
            except sessions.SessionError:
                errors.append("cancelled")

        def release():
            sessions.release("handover-test", wait=True)
            released.set()

        with tempfile.TemporaryDirectory() as folder, patch(
            "studio.gpu_lock.lock_path", return_value=Path(folder) / "gpu.lock"
        ), patch.object(sessions, "_Session", Starting):
            worker = threading.Thread(target=load)
            worker.start()
            self.assertTrue(acquired.wait(3))
            stopper = threading.Thread(target=release)
            stopper.start()
            self.assertFalse(released.wait(0.05), "Cannot hand GPU over during startup")
            proceed.set()
            worker.join(4)
            stopper.join(4)
            self.assertTrue(closed.is_set() and released.is_set())
            self.assertEqual(errors, ["cancelled"])
            lock = gpu_lock.try_acquire("handover-test")
            self.assertIsNotNone(lock)
            lock.close()
