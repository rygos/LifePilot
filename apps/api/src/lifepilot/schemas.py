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
