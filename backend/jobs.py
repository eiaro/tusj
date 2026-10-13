"""The last print jobs, kept in memory for troubleshooting and "print again".

Cleared when the backend restarts.
"""
import itertools
import threading
from collections import deque
from datetime import datetime, timezone

MAX_JOBS = 50


class JobLog:
    def __init__(self, max_jobs: int = MAX_JOBS):
        self._jobs: deque[dict] = deque(maxlen=max_jobs)
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def add(self, *, label_type: str, label_name, values: dict, lang: str, printer: str, copies: int,
            status: str | None = None, error: dict | None = None) -> dict:
        job = {
            "id": next(self._ids),
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "label_type": label_type,
            "label_name": label_name,
            "values": values,
            "lang": lang,
            "printer": printer,
            "copies": copies,
            "status": status,
            "error": error,
        }
        with self._lock:
            self._jobs.appendleft(job)
        return job

    def list(self) -> list[dict]:
        """Newest first."""
        with self._lock:
            return list(self._jobs)

    def get(self, job_id: int) -> dict | None:
        with self._lock:
            return next((j for j in self._jobs if j["id"] == job_id), None)

    def clear(self):
        with self._lock:
            self._jobs.clear()
            self._ids = itertools.count(1)
