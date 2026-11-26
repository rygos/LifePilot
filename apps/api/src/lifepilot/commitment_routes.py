from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.models import AuditEvent, Commitment, Conversation, Person, Project, Task, User, WorkCheckpoint
from lifepilot.security import current_user

router = APIRouter(prefix="/api", tags=["Verpflichtungen und Arbeitsstände"])
Direction = Literal["outgoing", "incoming"]
CommitmentStatus = Literal["open", "done", "cancelled"]


class CommitmentIn(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    notes: str = Field(default="", max_length=20000)
    direction: Direction
    person_id: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None
    due_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Titel darf nicht leer sein")
        return value.strip()

    @field_validator("due_at")
    @classmethod
    def normalize_due(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("Zeitpunkt benötigt eine Zeitzone")
            return value.astimezone(timezone.utc)
        return None


class CommitmentOut(CommitmentIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: CommitmentStatus
    source_capture_id: str | None = None
    source_quote: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("due_at", mode="before")
    @classmethod
    def stored_due(cls, value):
        return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value


class CommitmentState(BaseModel):
    status: CommitmentStatus


class CheckpointIn(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    progress: str = Field(default="", max_length=20000)
    blocker: str = Field(default="", max_length=10000)
    next_step: str = Field(min_length=1, max_length=10000)
    resources: str = Field(default="", max_length=20000)
    task_id: str | None = None
    project_id: str | None = None

    @field_validator("title", "next_step")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Bitte einen konkreten Wert eingeben")
        return value.strip()


class CheckpointOut(CheckpointIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    archived: bool
    created_at: datetime
    updated_at: datetime


class CheckpointState(BaseModel):
    archived: bool


def owned(db: Session, model, owner_id: str, resource_id: str):
    row = db.scalar(select(model).where(model.id == resource_id, model.owner_id == owner_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    return row


def validate_links(db: Session, owner_id: str, data):
    for field, model in (("person_id", Person), ("project_id", Project), ("conversation_id", Conversation), ("task_id", Task)):
        value = getattr(data, field, None)
        if value is not None:
            owned(db, model, owner_id, value)


def persist(db: Session, row, action: str, source: str):
    db.add(row)
    db.flush()
    db.add(AuditEvent(owner_id=row.owner_id, action=action, resource_type=row.__tablename__, resource_id=row.id, source=source))
    db.commit()
    db.refresh(row)
    return row


def list_commitments(db: Session, owner_id: str, status: CommitmentStatus | None = "open", direction: Direction | None = None, limit: int = 100, offset: int = 0):
    stmt = select(Commitment).where(Commitment.owner_id == owner_id)
    if status is not None:
        stmt = stmt.where(Commitment.status == status)
    if direction is not None:
        stmt = stmt.where(Commitment.direction == direction)
    return list(db.scalars(stmt.order_by(Commitment.due_at.is_(None), Commitment.due_at, Commitment.created_at.desc(), Commitment.id).offset(offset).limit(limit)))


def create_commitment(db: Session, owner_id: str, data: CommitmentIn, source: str = "web"):
    validate_links(db, owner_id, data)
    return persist(db, Commitment(owner_id=owner_id, **data.model_dump()), "create", source)


def set_commitment_status(db: Session, owner_id: str, resource_id: str, status: CommitmentStatus, source: str = "web"):
    row = owned(db, Commitment, owner_id, resource_id)
    if row.status == status:
        return row
    row.status = status
    return persist(db, row, "update", source)


def list_checkpoints(db: Session, owner_id: str, archived: bool = False, limit: int = 100, offset: int = 0):
    return list(db.scalars(select(WorkCheckpoint).where(WorkCheckpoint.owner_id == owner_id, WorkCheckpoint.archived == archived).order_by(WorkCheckpoint.updated_at.desc(), WorkCheckpoint.id).offset(offset).limit(limit)))


def create_checkpoint(db: Session, owner_id: str, data: CheckpointIn, source: str = "web"):
    validate_links(db, owner_id, data)
    return persist(db, WorkCheckpoint(owner_id=owner_id, **data.model_dump()), "create", source)


@router.get("/commitments", response_model=list[CommitmentOut])
def commitment_list(db: Session = Depends(get_db), user: User = Depends(current_user), status: CommitmentStatus | Literal["all"] = "open", direction: Direction | None = None, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    return list_commitments(db, user.id, None if status == "all" else status, direction, limit, offset)


@router.post("/commitments", response_model=CommitmentOut, status_code=201)
def commitment_create(data: CommitmentIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return create_commitment(db, user.id, data)


@router.put("/commitments/{resource_id}", response_model=CommitmentOut)
def commitment_update(resource_id: str, data: CommitmentIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = owned(db, Commitment, user.id, resource_id)
    validate_links(db, user.id, data)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    return persist(db, row, "update", "web")


@router.patch("/commitments/{resource_id}/status", response_model=CommitmentOut)
def commitment_status(resource_id: str, data: CommitmentState, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return set_commitment_status(db, user.id, resource_id, data.status)


@router.get("/checkpoints", response_model=list[CheckpointOut])
def checkpoint_list(db: Session = Depends(get_db), user: User = Depends(current_user), archived: bool = False, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    return list_checkpoints(db, user.id, archived, limit, offset)


@router.post("/checkpoints", response_model=CheckpointOut, status_code=201)
def checkpoint_create(data: CheckpointIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return create_checkpoint(db, user.id, data)


@router.get("/checkpoints/{resource_id}", response_model=CheckpointOut)
def checkpoint_get(resource_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return owned(db, WorkCheckpoint, user.id, resource_id)


@router.put("/checkpoints/{resource_id}", response_model=CheckpointOut)
def checkpoint_update(resource_id: str, data: CheckpointIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = owned(db, WorkCheckpoint, user.id, resource_id)
    validate_links(db, user.id, data)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    return persist(db, row, "update", "web")


@router.patch("/checkpoints/{resource_id}/archive", response_model=CheckpointOut)
def checkpoint_archive(resource_id: str, data: CheckpointState, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = owned(db, WorkCheckpoint, user.id, resource_id)
    if row.archived == data.archived:
        return row
    row.archived = data.archived
    return persist(db, row, "update", "web")
