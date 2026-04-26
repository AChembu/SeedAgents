from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class GenerateRequest(BaseModel):
    listing_url: HttpUrl | None = None
    address: str | None = None
    voice_style: str = "friendly luxury real-estate tour"
    include_neighborhood_copy: bool = True
    max_photos: int = Field(default=8, ge=2, le=12)


class ListingData(BaseModel):
    title: str
    description: str
    address: str | None = None
    image_urls: list[HttpUrl]
    source_url: HttpUrl | None = None


class Storyboard(BaseModel):
    hook: str
    scenes: list[str]
    cta: str
    full_script: str


class JobView(BaseModel):
    id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    progress: str | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)
