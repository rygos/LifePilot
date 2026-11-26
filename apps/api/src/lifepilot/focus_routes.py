from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifepilot.commitment_routes import CheckpointIn
from lifepilot.db import get_db
from lifepilot.models import AuditEvent, FocusSession, Task, User, WorkCheckpoint
from lifepilot.security import current_user

router = APIRouter(prefix="/api/focus", tags=["Fokus"])


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class FocusStart(BaseModel):
    task_id: str
    planned_minutes: int = Field(default=25, ge=1, le=180)


class FocusInterruption(BaseModel):
    progress: str = Field(default="", max_length=20000)
    blocker: str = Field(default="", max_length=10000)
    next_step: str = Field(min_length=1, max_length=10000)
    resources: str = Field(default="", max_length=20000)


class FocusEnd(BaseModel):
    outcome: Literal["finished", "interrupted"]
    checkpoint: FocusInterruption | None = None


class FocusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    task_id: str | None
    task_title: str
    planned_minutes: int
    started_at: datetime
    ended_at: datetime | None
    elapsed_seconds: int | None
    outcome: str | None
    checkpoint_id: str | None

    @field_serializer("started_at", "ended_at")
    def serialize_date(self, value: datetime | None):
        return utc(value).isoformat() if value is not None else None


def active_focus(db: Session, owner: str):
    return db.scalar(select(FocusSession).where(FocusSession.owner_id == owner, FocusSession.ended_at.is_(None)))


def start_focus(db: Session, owner: str, data: FocusStart, source: str = "rest"):
    task = db.scalar(select(Task).where(Task.id == data.task_id, Task.owner_id == owner))
    if task is None:
        raise HTTPException(404, "Aufgabe nicht gefunden")
    if task.status != "open":
        raise HTTPException(409, "Nur offene Aufgaben können fokussiert werden")
    if active_focus(db, owner) is not None:
        raise HTTPException(409, "Es läuft bereits eine Fokussitzung")
    row = FocusSession(owner_id=owner, task_id=task.id, task_title=task.title, planned_minutes=data.planned_minutes)
    db.add(row)
    try:
        db.flush()
        db.add(AuditEvent(owner_id=owner, action="create", resource_type="focus_sessions", resource_id=row.id, source=source))
        db.commit()
    except IntegrityError:
        db.rollback()
        if active_focus(db, owner) is not None:
            raise HTTPException(409, "Es läuft bereits eine Fokussitzung") from None
        raise
    db.refresh(row)
    return row


def end_focus(db: Session, owner: str, session_id: str, data: FocusEnd, source: str = "rest"):
    row = db.scalar(select(FocusSession).where(FocusSession.id == session_id, FocusSession.owner_id == owner).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, "Fokussitzung nicht gefunden")
    if row.ended_at is not None:
        return row
    if data.outcome == "finished" and data.checkpoint is not None:
        raise HTTPException(422, "Arbeitsstand ist nur für Unterbrechungen vorgesehen")
    if data.checkpoint is not None:
        try:
            checkpoint = CheckpointIn(title=row.task_title, task_id=row.task_id, **data.checkpoint.model_dump())
        except ValueError as exc:
            raise HTTPException(422, "Bitte einen konkreten nächsten Schritt eingeben") from exc
        task = db.scalar(select(Task).where(Task.id == row.task_id, Task.owner_id == owner)) if row.task_id else None
        values = checkpoint.model_dump()
        values["task_id"] = task.id if task else None
        values["project_id"] = task.project_id if task else None
        saved = WorkCheckpoint(owner_id=owner, **values)
        db.add(saved)
        db.flush()
        row.checkpoint_id = saved.id
        db.add(AuditEvent(owner_id=owner, action="create", resource_type="work_checkpoints", resource_id=saved.id, source=source))
    ended = datetime.now(timezone.utc)
    row.ended_at = ended
    row.elapsed_seconds = max(0, int((ended - utc(row.started_at)).total_seconds()))
    row.outcome = data.outcome
    db.add(AuditEvent(owner_id=owner, action="update", resource_type="focus_sessions", resource_id=row.id, source=source))
    db.commit()
    db.refresh(row)
    return row


def focus_history(db: Session, owner: str, limit: int = 50, offset: int = 0, task_id: str | None = None):
    stmt = select(FocusSession).where(FocusSession.owner_id == owner, FocusSession.ended_at.is_not(None))
    if task_id is not None:
        stmt = stmt.where(FocusSession.task_id == task_id)
    return list(db.scalars(stmt.order_by(FocusSession.started_at.desc(), FocusSession.id).offset(offset).limit(limit)))


@router.get("/active", response_model=FocusOut | None)
def get_active(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return active_focus(db, user.id)


@router.post("/start", response_model=FocusOut, status_code=201)
def start(data: FocusStart, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return start_focus(db, user.id, data)


@router.post("/{session_id}/end", response_model=FocusOut)
def end(session_id: str, data: FocusEnd, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return end_focus(db, user.id, session_id, data)


@router.get("/history", response_model=list[FocusOut])
def history(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), task_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return focus_history(db, user.id, limit, offset, task_id)
