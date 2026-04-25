from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

from .models import JobStatus, JobView


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass
class JobRecord:
    id: str
    status: JobStatus = JobStatus.queued
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    error: str | None = None
    progress: str | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)

    def to_view(self) -> JobView:
        return JobView(
            id=self.id,
            status=self.status,
            created_at=self.created_at,
            updated_at=self.updated_at,
            error=self.error,
            progress=self.progress,
            artifacts=self.artifacts,
        )


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = Lock()

    def create(self) -> JobRecord:
        with self._lock:
            job_id = str(uuid4())
            record = JobRecord(id=job_id)
            self._jobs[job_id] = record
            return record

    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        progress: str | None = None,
        error: str | None = None,
        artifacts: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            record = self._jobs[job_id]
            if status is not None:
                record.status = status
            if progress is not None:
                record.progress = progress
            if error is not None:
                record.error = error
            if artifacts is not None:
                record.artifacts.update(artifacts)
            record.updated_at = _utcnow()
