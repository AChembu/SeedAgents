from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class VisualScope(str, Enum):
    exterior = "exterior"
    interior = "interior"
    both = "both"


class PropertyStats(BaseModel):
    """Structured listing facts scraped from the page (best-effort)."""

    bedrooms: float | None = None
    bathrooms: float | None = None
    living_area_sqft: int | None = None
    lot_sqft: int | None = None
    year_built: int | None = None

    def has_any(self) -> bool:
        return any(
            v is not None
            for v in (
                self.bedrooms,
                self.bathrooms,
                self.living_area_sqft,
                self.lot_sqft,
                self.year_built,
            )
        )

    def to_overlay_lines(self) -> list[str]:
        """Short lines for on-video overlay (max two lines)."""
        if not self.has_any():
            return []
        parts: list[str] = []
        if self.bedrooms is not None:
            b = int(self.bedrooms) if self.bedrooms == int(self.bedrooms) else self.bedrooms
            parts.append(f"{b} bd")
        if self.bathrooms is not None:
            b = int(self.bathrooms) if self.bathrooms == int(self.bathrooms) else self.bathrooms
            parts.append(f"{b} ba")
        if self.living_area_sqft is not None:
            parts.append(f"{self.living_area_sqft:,} sq ft")
        line_a = " · ".join(parts) if parts else ""
        extras: list[str] = []
        if self.lot_sqft is not None:
            extras.append(f"Lot {self.lot_sqft:,} sq ft")
        if self.year_built is not None:
            extras.append(f"Built {self.year_built}")
        line_b = " · ".join(extras) if extras else ""
        lines = [line for line in (line_a, line_b) if line]
        return lines[:2]

    def to_sidebar_rows(self) -> list[tuple[str, str]]:
        """Label + value pairs for a vertical stats panel."""
        rows: list[tuple[str, str]] = []
        if self.bedrooms is not None:
            b = int(self.bedrooms) if self.bedrooms == int(self.bedrooms) else self.bedrooms
            rows.append(("Bedrooms", str(b)))
        if self.bathrooms is not None:
            b = int(self.bathrooms) if self.bathrooms == int(self.bathrooms) else self.bathrooms
            rows.append(("Bathrooms", str(b)))
        if self.living_area_sqft is not None:
            rows.append(("Living area", f"{self.living_area_sqft:,} sq ft"))
        if self.lot_sqft is not None:
            rows.append(("Lot size", f"{self.lot_sqft:,} sq ft"))
        if self.year_built is not None:
            rows.append(("Year built", str(self.year_built)))
        return rows

    def summary_sentence(self) -> str:
        """Single sentence for LLM prompts."""
        if not self.has_any():
            return ""
        bits: list[str] = []
        if self.bedrooms is not None:
            b = int(self.bedrooms) if self.bedrooms == int(self.bedrooms) else self.bedrooms
            bits.append(f"{b} bedrooms")
        if self.bathrooms is not None:
            b = int(self.bathrooms) if self.bathrooms == int(self.bathrooms) else self.bathrooms
            bits.append(f"{b} bathrooms")
        if self.living_area_sqft is not None:
            bits.append(f"{self.living_area_sqft:,} square feet")
        if self.lot_sqft is not None:
            bits.append(f"lot about {self.lot_sqft:,} square feet")
        if self.year_built is not None:
            bits.append(f"built in {self.year_built}")
        return ", ".join(bits)


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
    visual_scope: VisualScope = VisualScope.both


class ListingData(BaseModel):
    title: str
    description: str
    address: str | None = None
    image_urls: list[HttpUrl]
    source_url: HttpUrl | None = None
    stats: PropertyStats | None = None


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


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12_000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    property_context: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    reply: str
