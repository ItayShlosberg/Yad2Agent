"""Immutable message model used for conversation persistence."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class Message(BaseModel):
    direction: str  # "inbound" | "outbound"
    body: str
    at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
