"""Bound frequent engine progress writes so interactive commands can acquire SQLite."""
import time


class ProgressReporter:
    def __init__(self, store, job_id, interval=0.25, clock=time.monotonic):
        self.store, self.job_id, self.interval, self.clock = store, job_id, interval, clock
        self.last = None

    def __call__(self, message, current=None, total=None):
        now = self.clock()
        final = current is not None and total is not None and current >= total
        if current is not None and not final and self.last is not None and now - self.last < self.interval:
            return
        values = {"message": message}
        if current is not None:
            values.update(current=current, total=total)
        self.store.job_update(self.job_id, **values)
        self.last = self.clock()
