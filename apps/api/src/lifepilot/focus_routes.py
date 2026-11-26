from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifepilot.commitment_routes import CheckpointIn
from lifepilot.db import get_db
from lifepilot.models import AuditEvent, FocusCheckIn, FocusSession, Task, TaskStep, User, WorkCheckpoint
from lifepilot.security import current_user

router = APIRouter(prefix="/api/focus", tags=["Fokus"])


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class FocusStart(BaseModel):
    task_id: str
    planned_minutes: int = Field(default=25, ge=1, le=180)
    companion_interval_minutes: int | None = Field(default=None, ge=2, le=60)
    companion_goal: str = Field(default="", max_length=1000)


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
    companion_interval_minutes: int | None = None
    companion_goal: str = ""

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
    row = FocusSession(owner_id=owner, task_id=task.id, task_title=task.title, planned_minutes=data.planned_minutes, companion_interval_minutes=data.companion_interval_minutes, companion_goal=data.companion_goal.strip())
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


CheckInState = Literal["on_track", "distracted", "blocked", "skip"]


class CheckInIn(BaseModel):
    request_id: UUID
    state: CheckInState
    note: str = Field(default="", max_length=4000)
    next_step: str = Field(default="", max_length=1000)


class CheckInOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    state: CheckInState
    note: str
    next_step: str
    created_at: datetime

    @field_serializer("created_at")
    def serialize_date(self, value: datetime):
        return utc(value).isoformat()


class CompanionOut(BaseModel):
    interval_minutes: int | None
    goal: str
    next_due_at: datetime | None
    suggested_next_step: str
    checkins: list[CheckInOut]


def owned_focus(db: Session, owner: str, session_id: str, lock: bool = False):
    stmt = select(FocusSession).where(FocusSession.id == session_id, FocusSession.owner_id == owner)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(404, "Fokussitzung nicht gefunden")
    return row


def companion_context(db: Session, owner: str, session_id: str) -> CompanionOut:
    row = owned_focus(db, owner, session_id)
    checkins = list(db.scalars(select(FocusCheckIn).where(FocusCheckIn.owner_id == owner, FocusCheckIn.session_id == row.id).order_by(FocusCheckIn.created_at.desc(), FocusCheckIn.id.desc()).limit(50)))
    next_due_at = None
    if row.ended_at is None and row.companion_interval_minutes is not None:
        last = utc(checkins[0].created_at) if checkins else utc(row.started_at)
        due = last + timedelta(minutes=row.companion_interval_minutes)
        if due < utc(row.started_at) + timedelta(minutes=row.planned_minutes):
            next_due_at = due
    suggested = next((c.next_step for c in checkins if c.next_step.strip()), "")
    if not suggested and row.task_id:
        step = db.scalar(select(TaskStep).where(TaskStep.owner_id == owner, TaskStep.task_id == row.task_id, TaskStep.completed_at.is_(None)).order_by(TaskStep.position).limit(1))
        task = db.scalar(select(Task).where(Task.owner_id == owner, Task.id == row.task_id))
        suggested = step.title if step else (task.next_step or "" if task else "")
    return CompanionOut(interval_minutes=row.companion_interval_minutes, goal=row.companion_goal, next_due_at=next_due_at, suggested_next_step=suggested, checkins=[CheckInOut.model_validate(c) for c in checkins])


def record_checkin(db: Session, owner: str, session_id: str, data: CheckInIn, source: str = "rest") -> CompanionOut:
    row = owned_focus(db, owner, session_id, lock=True)
    existing = db.scalar(select(FocusCheckIn).where(FocusCheckIn.session_id == row.id, FocusCheckIn.owner_id == owner, FocusCheckIn.request_id == str(data.request_id)))
    if existing is not None:
        return companion_context(db, owner, session_id)
    if row.ended_at is not None or row.companion_interval_minutes is None:
        raise HTTPException(409, "Der Arbeitsbegleiter ist nicht aktiv")
    if data.state == "skip" and (data.note.strip() or data.next_step.strip()):
        raise HTTPException(422, "Übersprungene Check-ins enthalten keine Notizen")
    checkin = FocusCheckIn(owner_id=owner, session_id=row.id, request_id=str(data.request_id), state=data.state, note=data.note.strip(), next_step=data.next_step.strip())
    db.add(checkin)
    db.flush()
    db.add(AuditEvent(owner_id=owner, action="create", resource_type="focus_checkins", resource_id=checkin.id, source=source))
    db.commit()
    return companion_context(db, owner, session_id)


@router.get("/{session_id}/companion", response_model=CompanionOut)
def get_companion(session_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return companion_context(db, user.id, session_id)


@router.post("/{session_id}/checkins", response_model=CompanionOut)
def post_checkin(session_id: str, data: CheckInIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return record_checkin(db, user.id, session_id, data)
