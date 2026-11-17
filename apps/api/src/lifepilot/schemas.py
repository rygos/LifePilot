from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

class Credentials(BaseModel):
    username: str
    password: str
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
class PersonIn(BaseModel):
    first_name: str
    last_name: str = ""
    nickname: str | None = None
    birthday: str | None = None
    email: str | None = None
    phone: str | None = None
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
class TaskIn(BaseModel):
    title: str
    description: str = ""
    person_id: str | None = None
    due_at: datetime | None = None
    priority: int = Field(default=2, ge=1, le=3)
class TaskOut(TaskIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: str
class RelationshipIn(BaseModel):
    source_person_id: str
    target_person_id: str
    relationship_type: str
    source_memory_id: str | None = None
    confirmed: bool = True

class ConversationIn(BaseModel):
    title: str
    original_note: str
    participant_ids: list[str] = Field(default_factory=list)
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
