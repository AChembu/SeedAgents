from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .job_store import InMemoryJobStore
from .models import GenerateRequest, JobStatus, JobView
from .pipeline import run_generation_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()
job_store = InMemoryJobStore()
app = FastAPI(title="SeedEstate Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _set_state(job_id: str, **kwargs) -> None:
    job_store.update(job_id, **kwargs)


async def _execute(job_id: str, payload: GenerateRequest) -> None:
    logger.info(
        "job=%s execute_start listing_url=%s address=%s max_photos=%s",
        job_id,
        bool(payload.listing_url),
        bool(payload.address),
        payload.max_photos,
    )
    try:
        artifacts = await run_generation_job(
            settings=settings,
            request=payload,
            job_id=job_id,
            set_state=lambda **kwargs: _set_state(job_id, **kwargs),
        )
        _set_state(job_id, status=JobStatus.completed, progress="Done", artifacts=artifacts)
        logger.info("job=%s execute_completed", job_id)
    except Exception as exc:  # noqa: BLE001
        _set_state(job_id, status=JobStatus.failed, error=str(exc), progress="Failed")
        logger.exception("job=%s execute_failed", job_id)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/generate", response_model=JobView)
async def create_generation(payload: GenerateRequest) -> JobView:
    if not payload.listing_url and not payload.address:
        raise HTTPException(status_code=400, detail="Provide either listing_url or address.")

    job = job_store.create()
    logger.info("job=%s queued", job.id)
    asyncio.create_task(_execute(job.id, payload))
    return job.to_view()


@app.get("/api/jobs/{job_id}", response_model=JobView)
async def get_job(job_id: str) -> JobView:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_view()


output_dir = Path(settings.output_dir)
output_dir.mkdir(parents=True, exist_ok=True)
app.mount("/generated", StaticFiles(directory=str(output_dir)), name="generated")
