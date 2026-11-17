from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator


class CaptureIn(BaseModel):
    original_text: str = Field(min_length=1, max_length=20000)


class CaptureSuggestion(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=4000)
    person_name: str | None = Field(default=None, max_length=240)
    occurred_at: datetime | None = None


class CaptureReview(BaseModel):
    accepted_indices: list[int] = Field(max_length=100)


class AcceptedMemory(BaseModel):
    id: str
    title: str


class CaptureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_text: str
    status: Literal["pending", "ready", "unavailable", "failed", "reviewed"]
    suggestions: list[CaptureSuggestion]
    processing_error: str
    created_at: datetime
    reviewed_at: datetime | None

    @field_validator("suggestions", mode="before")
    @classmethod
    def parse_suggestions(cls, value: str | list[CaptureSuggestion]) -> list[CaptureSuggestion]:
        if isinstance(value, str):
            return TypeAdapter(list[CaptureSuggestion]).validate_json(value)
        return value
