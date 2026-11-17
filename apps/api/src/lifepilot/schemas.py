from datetime import datetime, time, timezone
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

class Credentials(BaseModel):
    username: str
    password: str
class MCPTokenRequest(Credentials):
    access: str = Field(default="read_only", pattern="^(read_only|read_write)$")
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class ProjectIn(BaseModel):
    name: str
    description: str = ""
    status: str = Field(default="active", pattern="^(active|paused|completed|archived)$")

class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = Field(default=None, pattern="^(active|paused|completed|archived)$")

class ProjectOut(ProjectIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime

class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    operation: str
    resource_id: str
    resource_label: str
    status: str
    created_at: datetime
    decided_at: datetime | None

class ReindexOut(BaseModel):
    queued: int
    failed: int
    semantic_enabled: bool
class PersonIn(BaseModel):
    first_name: str
    last_name: str = ""
    nickname: str | None = None
    birthday: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str = ""
    website: str | None = None
    job_title: str | None = None
    organization: str | None = None
    notes: str = ""
class PersonOut(PersonIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
class MemoryIn(BaseModel):
    title: str
    content: str
    person_id: str | None = None
    occurred_at: datetime | None = None
    source: str = "manual"
class MemoryOut(MemoryIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    source_capture_id: str | None = None
class TaskIn(BaseModel):
    title: str
    description: str = ""
    person_id: str | None = None
    project_id: str | None = None
    due_at: datetime | None = None
    priority: int = Field(default=2, ge=1, le=3)
    repeat_interval_days: int | None = Field(default=None, ge=1, le=365)
    repeat_until: datetime | None = None

    @model_validator(mode="after")
    def recurrence_requires_due_date(self) -> Self:
        if self.repeat_interval_days is not None and self.due_at is None:
            raise ValueError("Wiederholende Aufgaben benötigen ein Fälligkeitsdatum")
        if self.repeat_until is not None and (self.repeat_interval_days is None or self.due_at is None):
            raise ValueError("Ein Enddatum benötigt eine Wiederholung und ein Fälligkeitsdatum")
        if self.repeat_until is not None and self.due_at is not None:
            if (self.repeat_until.utcoffset() is None) != (self.due_at.utcoffset() is None):
                raise ValueError("Fälligkeitsdatum und Wiederholungsende müssen dieselbe Zeitzonenart verwenden")
            if self.repeat_until <= self.due_at:
                raise ValueError("Das Wiederholungsende muss nach dem ersten Fälligkeitsdatum liegen")
        return self
class TaskOut(TaskIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: str

    @field_serializer("due_at", "repeat_until")
    def serialize_dates_as_utc(self, value: datetime | None) -> datetime | None:
        return as_utc(value)
class RelationshipIn(BaseModel):
    source_person_id: str
    target_person_id: str
    relationship_type: str
    inverse_relationship_type: str | None = None
    source_memory_id: str | None = None
    confirmed: bool = True

class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    username: str
    full_name: str
    nickname: str | None
    birthday: str | None
    email: str | None
    phone: str | None
    address: str
    timezone_name: str
    quiet_hours_start: time | None
    quiet_hours_end: time | None

class ProfileUpdate(BaseModel):
    full_name: str = ""
    nickname: str | None = None
    birthday: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str = ""
    timezone_name: str = Field(default="Europe/Berlin", min_length=1, max_length=64)
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None

    @field_validator("timezone_name")
    @classmethod
    def timezone_must_exist(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Unbekannte Zeitzone") from error
        return value

    @model_validator(mode="after")
    def quiet_hours_must_be_a_pair(self) -> Self:
        quiet_fields = {"quiet_hours_start", "quiet_hours_end"}
        submitted = quiet_fields & self.model_fields_set
        if submitted and submitted != quiet_fields:
            raise ValueError("Ruhezeit benötigt Start und Ende")
        if submitted == quiet_fields:
            if (self.quiet_hours_start is None) != (self.quiet_hours_end is None):
                raise ValueError("Ruhezeit benötigt Start und Ende")
            if self.quiet_hours_start == self.quiet_hours_end and self.quiet_hours_start is not None:
                raise ValueError("Start und Ende der Ruhezeit dürfen nicht gleich sein")
        return self

class RelationshipOut(BaseModel):
    id: str
    source_person_id: str
    source_person_name: str
    target_person_id: str
    target_person_name: str
    relationship_type: str
    inverse_relationship_type: str
    confirmed: bool
    source_memory_id: str | None

class ConversationIn(BaseModel):
    title: str
    original_note: str
    participant_ids: list[str] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)
    occurred_at: datetime | None = None
    location: str = ""
    summary: str = ""

class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    original_note: str
    summary: str
    location: str
    occurred_at: datetime | None
    created_at: datetime
    participant_ids: list[str]
    project_ids: list[str] = Field(default_factory=list)

class LoanIn(BaseModel):
    item_name: str
    lender_person_id: str | None = None
    borrower_person_id: str | None = None
    lent_at: datetime | None = None
    due_at: datetime | None = None
    condition_note: str = ""
    source_memory_id: str | None = None

class LoanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    item_name: str
    lender_person_id: str | None
    borrower_person_id: str | None
    lent_at: datetime
    due_at: datetime | None
    returned_at: datetime | None
    condition_note: str
    source_memory_id: str | None

class GiftIn(BaseModel):
    person_id: str
    title: str
    note: str = ""
    occasion: str = ""
    budget: int | None = Field(default=None, ge=0)
    status: str = "idea"
    source_memory_id: str | None = None

class GiftOut(GiftIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime

class EventIn(BaseModel):
    title: str
    description: str = ""
    location: str = ""
    starts_at: datetime
    ends_at: datetime | None = None
    participant_ids: list[str] = Field(default_factory=list)
    source_memory_id: str | None = None

class EventPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    location: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    participant_ids: list[str] | None = None
    source_memory_id: str | None = None

    @model_validator(mode="after")
    def required_fields_cannot_be_cleared(self) -> Self:
        required_fields = {"title", "description", "location", "starts_at", "participant_ids"}
        if any(getattr(self, field) is None for field in required_fields & self.model_fields_set):
            raise ValueError("Pflichtfelder eines Termins dürfen nicht geleert werden")
        return self

class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    description: str
    location: str
    starts_at: datetime
    ends_at: datetime | None
    source_memory_id: str | None
    participant_ids: list[str]

    @field_serializer("starts_at", "ends_at")
    def serialize_dates_as_utc(self, value: datetime | None) -> datetime | None:
        return as_utc(value)

class ReminderIn(BaseModel):
    title: str
    due_at: datetime
    task_id: str | None = None
    event_id: str | None = None

class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    due_at: datetime
    state: str
    snoozed_until: datetime | None
    task_id: str | None
    event_id: str | None

    @field_serializer("due_at", "snoozed_until")
    def serialize_dates_as_utc(self, value: datetime | None) -> datetime | None:
        return as_utc(value)

class ReminderAction(BaseModel):
    state: str
    snoozed_until: datetime | None = None
