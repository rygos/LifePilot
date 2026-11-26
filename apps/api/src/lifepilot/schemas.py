from datetime import date, datetime, time, timezone
from typing import Literal, Self
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
    family_read: bool = False
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
Gender = Literal["female", "male", "diverse", "unspecified"]

ContactMethodType = Literal["email", "phone", "address", "website", "messaging", "social", "other"]
AttachmentResourceType = Literal["person", "memory", "conversation", "event", "project"]

class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    resource_type: AttachmentResourceType
    resource_id: str
    file_name: str
    content_type: str
    size_bytes: int
    created_at: datetime

class ContactMethodIn(BaseModel):
    method_type: ContactMethodType
    label: str = Field(default="", max_length=80)
    value: str = Field(min_length=1, max_length=1000)

    @field_validator("label", "value")
    @classmethod
    def trim_contact_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("value")
    @classmethod
    def require_contact_value(cls, value: str) -> str:
        if not value:
            raise ValueError("Bitte einen Kontaktwert angeben")
        return value

class ContactMethodOut(ContactMethodIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    person_id: str
    created_at: datetime


class PersonIn(BaseModel):
    first_name: str
    last_name: str = ""
    nickname: str | None = None
    birthday: str | None = None
    birthday_precision: Literal["exact", "month_day", "approximate", "unknown"] = "unknown"
    birthday_month: int | None = Field(default=None, ge=1, le=12)
    birthday_day: int | None = Field(default=None, ge=1, le=31)
    birthday_approximate_age: int | None = Field(default=None, ge=0, le=130)
    contact_interval_days: int | None = Field(default=None, ge=1, le=365)
    gender: Gender | None = None
    email: str | None = None
    phone: str | None = None
    address: str = ""
    website: str | None = None
    job_title: str | None = None
    organization: str | None = None
    how_met: str = ""
    tags: list[str] = Field(default_factory=list, max_length=30)
    is_favorite: bool = False
    notes: str = ""

    @model_validator(mode="after")
    def validate_birthday_precision(self) -> Self:
        if self.birthday:
            try:
                birth_date = date.fromisoformat(self.birthday)
            except ValueError as error:
                raise ValueError("Geburtstag muss ein gültiges Datum sein") from error
            if self.birthday_precision == "unknown":
                self.birthday_precision = "exact"
            if self.birthday_precision != "exact":
                raise ValueError("Ein genaues Geburtsdatum benötigt die Genauigkeit 'genau'")
            self.birthday_month = birth_date.month
            self.birthday_day = birth_date.day
            self.birthday_approximate_age = None
        elif self.birthday_precision == "exact":
            raise ValueError("Bitte das genaue Geburtsdatum angeben")
        elif self.birthday_precision == "month_day":
            if self.birthday_month is None or self.birthday_day is None:
                raise ValueError("Bitte Tag und Monat des Geburtstags angeben")
            try:
                date(2000, self.birthday_month, self.birthday_day)
            except ValueError as error:
                raise ValueError("Dieser Geburtstag ist kein gültiges Kalenderdatum") from error
            self.birthday_approximate_age = None
        elif self.birthday_precision == "approximate":
            if self.birthday_approximate_age is None:
                raise ValueError("Bitte das ungefähre Alter angeben")
            self.birthday_month = None
            self.birthday_day = None
        else:
            self.birthday_month = None
            self.birthday_day = None
            self.birthday_approximate_age = None
        return self

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        normalized: dict[str, str] = {}
        for value in values:
            tag = " ".join(value.strip().split())
            if not tag:
                continue
            if len(tag) > 40:
                raise ValueError("Labels dürfen höchstens 40 Zeichen lang sein")
            normalized.setdefault(tag.casefold(), tag)
        if len(normalized) > 30:
            raise ValueError("Pro Person sind höchstens 30 Labels erlaubt")
        return list(normalized.values())

class PersonPatch(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    nickname: str | None = None
    birthday: str | None = None
    birthday_precision: Literal["exact", "month_day", "approximate", "unknown"] | None = None
    birthday_month: int | None = Field(default=None, ge=1, le=12)
    birthday_day: int | None = Field(default=None, ge=1, le=31)
    birthday_approximate_age: int | None = Field(default=None, ge=0, le=130)
    contact_interval_days: int | None = Field(default=None, ge=1, le=365)
    gender: Gender | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    website: str | None = None
    job_title: str | None = None
    organization: str | None = None
    how_met: str | None = None
    tags: list[str] | None = Field(default=None, max_length=30)
    is_favorite: bool | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_partial_birthday(self) -> Self:
        fields = self.model_fields_set
        precision = self.birthday_precision
        if precision is None and fields.intersection({"birthday", "birthday_month", "birthday_day", "birthday_approximate_age"}):
            if "birthday" in fields and self.birthday is None and not fields.intersection({"birthday_month", "birthday_day", "birthday_approximate_age"}):
                self.birthday_precision = "unknown"
                self.birthday_month = None
                self.birthday_day = None
                self.birthday_approximate_age = None
                return self
            raise ValueError("Beim Ändern eines Geburtstags muss auch die Genauigkeit angegeben werden")
        if precision == "exact":
            if not self.birthday:
                raise ValueError("Bitte das genaue Geburtsdatum angeben")
            try:
                birth_date = date.fromisoformat(self.birthday)
            except ValueError as error:
                raise ValueError("Geburtstag muss ein gültiges Datum sein") from error
            self.birthday_month = birth_date.month
            self.birthday_day = birth_date.day
            self.birthday_approximate_age = None
        elif precision == "month_day":
            if self.birthday_month is None or self.birthday_day is None:
                raise ValueError("Bitte Tag und Monat des Geburtstags angeben")
            try:
                date(2000, self.birthday_month, self.birthday_day)
            except ValueError as error:
                raise ValueError("Dieser Geburtstag ist kein gültiges Kalenderdatum") from error
            self.birthday = None
            self.birthday_approximate_age = None
        elif precision == "approximate":
            if self.birthday_approximate_age is None:
                raise ValueError("Bitte das ungefähre Alter angeben")
            self.birthday = None
            self.birthday_month = None
            self.birthday_day = None
        elif precision == "unknown":
            self.birthday = None
            self.birthday_month = None
            self.birthday_day = None
            self.birthday_approximate_age = None
        return self

    @field_validator("tags")
    @classmethod
    def normalize_patch_tags(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized: dict[str, str] = {}
        for value in values:
            tag = " ".join(value.strip().split())
            if tag:
                normalized.setdefault(tag.casefold(), tag)
        if len(normalized) > 30:
            raise ValueError("Pro Person sind höchstens 30 Labels erlaubt")
        if any(len(tag) > 40 for tag in normalized.values()):
            raise ValueError("Labels dürfen höchstens 40 Zeichen lang sein")
        return list(normalized.values())

class PersonOut(PersonIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    is_self: bool = False
    photo_key: str | None = None
    created_at: datetime
    gender: Gender = "unspecified"
    contact_methods: list[ContactMethodOut] = Field(default_factory=list)

class OrganizationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    organization_type: str = Field(default="club", pattern="^(club|company|school|other)$")
    notes: str = ""

class OrganizationOut(OrganizationIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    members: list[dict] = Field(default_factory=list)

class MembershipIn(BaseModel):
    organization_id: str
    role: str = Field(default="", max_length=160)
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("Das Ende der Mitgliedschaft muss nach dem Beginn liegen")
        return self

class MembershipOut(BaseModel):
    id: str
    person_id: str
    person_name: str
    person_photo_key: str | None
    person_birthday: str | None
    organization_id: str
    organization_name: str
    organization_type: str
    role: str
    valid_from: datetime | None
    valid_until: datetime | None
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

JournalMood = Literal["freudig", "ruhig", "neutral", "traurig", "gestresst", "dankbar", "energiegeladen"]

class JournalEntryIn(BaseModel):
    entry_date: date
    title: str = Field(default="", max_length=240)
    content: str = Field(min_length=1, max_length=20000)
    mood: JournalMood | None = None
    person_ids: list[str] = Field(default_factory=list, max_length=50)
    project_ids: list[str] = Field(default_factory=list, max_length=50)
    event_ids: list[str] = Field(default_factory=list, max_length=50)

class JournalEntryPatch(BaseModel):
    entry_date: date | None = None
    title: str | None = Field(default=None, max_length=240)
    content: str | None = Field(default=None, min_length=1, max_length=20000)
    mood: JournalMood | None = None
    person_ids: list[str] | None = Field(default=None, max_length=50)
    project_ids: list[str] | None = Field(default=None, max_length=50)
    event_ids: list[str] | None = Field(default=None, max_length=50)

class JournalEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    entry_date: date
    title: str
    content: str
    mood: JournalMood | None
    person_ids: list[str]
    project_ids: list[str]
    event_ids: list[str]
    created_at: datetime
    updated_at: datetime

PetRelationshipType = Literal["owner", "caretaker", "lives_with"]
PetSex = Literal["female", "male", "unknown"]

class PetPersonLinkIn(BaseModel):
    person_id: str
    relationship_type: PetRelationshipType = "owner"

class PetPersonLinkOut(PetPersonLinkIn):
    pass

class PetIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    species: str = Field(min_length=1, max_length=80)
    breed: str = Field(default="", max_length=120)
    sex: PetSex = "unknown"
    birthday: date | None = None
    is_neutered: bool = False
    notes: str = Field(default="", max_length=20000)
    person_links: list[PetPersonLinkIn] = Field(default_factory=list, max_length=50)
    event_ids: list[str] = Field(default_factory=list, max_length=50)

class PetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    species: str | None = Field(default=None, min_length=1, max_length=80)
    breed: str | None = Field(default=None, max_length=120)
    sex: PetSex | None = None
    birthday: date | None = None
    is_neutered: bool | None = None
    notes: str | None = Field(default=None, max_length=20000)
    person_links: list[PetPersonLinkIn] | None = Field(default=None, max_length=50)
    event_ids: list[str] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def required_pet_fields_cannot_be_cleared(self) -> Self:
        required = {"name", "species", "sex", "is_neutered"}
        if any(getattr(self, field) is None for field in required & self.model_fields_set):
            raise ValueError("Pflichtangaben des Tierprofils dürfen nicht geleert werden")
        return self

class PetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    species: str
    breed: str
    sex: PetSex
    birthday: date | None
    is_neutered: bool
    notes: str
    person_links: list[PetPersonLinkOut]
    event_ids: list[str]
    created_at: datetime
    updated_at: datetime

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
    estimated_minutes: int | None = None
    mental_effort: str | None = None
    start_friction: str | None = None
    work_context: str | None = None
    next_step: str | None = None
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

class RelationshipWithPersonIn(BaseModel):
    source_person_id: str
    relationship_type: str = Field(min_length=1, max_length=100)
    new_person: PersonIn

class PersonCallIn(BaseModel):
    occurred_at: datetime
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    notes: str = Field(default="", max_length=5000)

    @field_validator("occurred_at")
    @classmethod
    def normalize_call_time(cls, value: datetime) -> datetime:
        return as_utc(value) or value

    @field_validator("notes")
    @classmethod
    def trim_call_notes(cls, value: str) -> str:
        return value.strip()

class PersonCallOut(PersonCallIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    person_id: str
    created_at: datetime

    @field_serializer("occurred_at", "created_at")
    def serialize_call_dates_as_utc(self, value: datetime) -> datetime:
        return as_utc(value) or value

class UserPersonRelationshipIn(BaseModel):
    relationship_type: str = Field(min_length=1, max_length=100)
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        if self.valid_from and self.valid_until and as_utc(self.valid_until) < as_utc(self.valid_from):
            raise ValueError("Das Ende der Beziehung darf nicht vor ihrem Beginn liegen")
        return self

class UserPersonRelationshipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    person_id: str
    relationship_type: str
    valid_from: datetime | None
    valid_until: datetime | None
    source_capture_id: str | None
    confirmed: bool

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
    self_person_id: str = ""

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

class ConversationPatch(BaseModel):
    title: str | None = None
    original_note: str | None = None
    summary: str | None = None
    location: str | None = None
    occurred_at: datetime | None = None
    participant_ids: list[str] | None = None
    project_ids: list[str] | None = None

    @model_validator(mode="after")
    def required_fields_cannot_be_cleared(self) -> Self:
        required_fields = {"title", "original_note", "summary", "location"}
        if any(getattr(self, field) is None for field in required_fields & self.model_fields_set):
            raise ValueError("Pflichtfelder eines Gesprächs dürfen nicht geleert werden")
        return self

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

class RelationshipWithPersonOut(BaseModel):
    person: PersonOut
    relationship: RelationshipOut

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
    record_type: Literal["appointment", "experience"] = "appointment"
    description: str = ""
    location: str = ""
    location_address: str = ""
    starts_at: datetime
    ends_at: datetime | None = None
    participant_ids: list[str] = Field(default_factory=list)
    source_memory_id: str | None = None

class EventPatch(BaseModel):
    title: str | None = None
    record_type: Literal["appointment", "experience"] | None = None
    description: str | None = None
    location: str | None = None
    location_address: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    participant_ids: list[str] | None = None
    source_memory_id: str | None = None

    @model_validator(mode="after")
    def required_fields_cannot_be_cleared(self) -> Self:
        required_fields = {"title", "record_type", "description", "location", "location_address", "starts_at", "participant_ids"}
        if any(getattr(self, field) is None for field in required_fields & self.model_fields_set):
            raise ValueError("Pflichtfelder eines Termins dürfen nicht geleert werden")
        return self

class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    record_type: Literal["appointment", "experience"]
    description: str
    location: str
    location_address: str
    starts_at: datetime
    ends_at: datetime | None
    source_memory_id: str | None
    participant_ids: list[str]

    @field_serializer("starts_at", "ends_at")
    def serialize_dates_as_utc(self, value: datetime | None) -> datetime | None:
        return as_utc(value)

class EventPhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str
    caption: str
    created_at: datetime

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
    birthday_person_id: str | None = None
    birthday_year: int | None = None
    contact_person_id: str | None = None

    @field_serializer("due_at", "snoozed_until")
    def serialize_dates_as_utc(self, value: datetime | None) -> datetime | None:
        return as_utc(value)

class ReminderAction(BaseModel):
    state: str
    snoozed_until: datetime | None = None
