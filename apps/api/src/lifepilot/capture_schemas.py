from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator


CaptureKind = Literal["fact", "conversation", "relationship", "owner_relationship", "former_name", "life_event", "task", "event", "project_link", "loan"]
DatePrecision = Literal["exact", "day", "month", "year", "approximate", "unknown"]
Gender = Literal["female", "male", "diverse"]
GenderBasis = Literal["explicit", "name_inference"]


class CaptureIn(BaseModel):
    original_text: str = Field(min_length=1, max_length=20000)
    parent_capture_id: str | None = Field(default=None, max_length=36)
    source: Literal["capture", "chat"] = "capture"


class CaptureSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: CaptureKind = "fact"
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=4000)
    person_name: str | None = Field(default=None, max_length=240)
    person_gender: Gender | None = None
    person_gender_basis: GenderBasis | None = None
    person_id: str | None = Field(default=None, max_length=36)
    person_candidates: list[str] = Field(default_factory=list, max_length=5)
    former_name: str | None = Field(default=None, max_length=240)
    project_name: str | None = Field(default=None, max_length=240)
    project_id: str | None = Field(default=None, max_length=36)
    project_candidates: list[str] = Field(default_factory=list, max_length=5)
    relationship_type: str | None = Field(default=None, max_length=100)
    inverse_relationship_type: str | None = Field(default=None, max_length=100)
    related_person_name: str | None = Field(default=None, max_length=240)
    related_person_gender: Gender | None = None
    related_person_gender_basis: GenderBasis | None = None
    related_person_id: str | None = Field(default=None, max_length=36)
    related_person_candidates: list[str] = Field(default_factory=list, max_length=5)
    due_at: datetime | None = None
    occurred_at: datetime | None = None
    date_precision: DatePrecision = "unknown"
    confirmation_required: bool = False


class CaptureReviewIn(BaseModel):
    accepted_indices: list[int] = Field(max_length=100)
    person_assignments: dict[int, str] = Field(default_factory=dict)
    related_person_assignments: dict[int, str] = Field(default_factory=dict)
    project_assignments: dict[int, str] = Field(default_factory=dict)
    create_people: list[int] = Field(default_factory=list)
    create_related_people: list[int] = Field(default_factory=list)
    confirmations: list[int] = Field(default_factory=list)
    suggestions: list[CaptureSuggestion] | None = None


class AcceptedMemory(BaseModel):
    id: str
    title: str
    kind: CaptureKind = "fact"
    resource_id: str | None = None
    resource_type: str = "memory"


class CaptureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_capture_id: str | None = None
    original_text: str
    source: Literal["capture", "chat"] = "capture"
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
