"""Real SQLite job progress under a burst; log parsing is intentionally unchanged."""
import tempfile
import unittest

from studio.progress import ProgressReporter
from studio.store import Store


class ProgressTests(unittest.TestCase):
    def test_burst_keeps_writes_bounded_without_losing_final_state_or_stage_messages(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            pid = store.create("진행률")['id']
            job = store.new_job(pid, "train", {})
            now = [0.0]
            progress = ProgressReporter(store, job, clock=lambda: now[0])
            for it in range(1, 1000):
                progress("학습", it, 1000)
            self.assertEqual(store.job(job)['current'], 1)
            # Cancellation can write while the next engine ticks are coalesced.
            store.job_update(job, cancel_requested=1)
            self.assertTrue(store.job(job)['cancel_requested'])
            now[0] = 0.3
            progress("학습", 999, 1000)
            self.assertEqual(store.job(job)['current'], 999)
            progress("마지막 반복", 1000, 1000)
            self.assertEqual(store.job(job)['current'], 1000)
            progress("결과 저장 중")
            self.assertEqual(store.job(job)['message'], "결과 저장 중")
