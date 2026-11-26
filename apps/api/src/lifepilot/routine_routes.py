from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.models import AuditEvent, Routine, RoutineStep, RoutineCompletion, User
from lifepilot.security import current_user

router = APIRouter(prefix="/api/routines", tags=["Routinen"])


class RoutineSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=240)
    weekdays: list[int] = Field(min_length=1, max_length=7)
    window_start: time | None = None
    window_end: time | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Titel darf nicht leer sein")
        return value.strip()

    @field_validator("weekdays")
    @classmethod
    def valid_days(cls, value):
        if any(not 0 <= day <= 6 for day in value) or len(set(value)) != len(value):
            raise ValueError("Wochentage müssen eindeutig zwischen 0 (Montag) und 6 (Sonntag) liegen")
        return sorted(value)

    @model_validator(mode="after")
    def valid_window(self):
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("Zeitfenster benötigt Beginn und Ende")
        if self.window_start is not None and (self.window_start.tzinfo is not None or self.window_end.tzinfo is not None or self.window_start >= self.window_end):
            raise ValueError("Zeitfenster muss innerhalb eines lokalen Kalendertags liegen")
        return self


class RoutineStepIn(BaseModel):
    title: str = Field(min_length=1, max_length=240)

    @field_validator("title")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Schritt darf nicht leer sein")
        return value.strip()


class RoutineCreate(RoutineSchedule):
    steps: list[RoutineStepIn] = Field(min_length=1, max_length=30)


class ArchiveIn(BaseModel):
    archived: bool


class CompletionIn(BaseModel):
    completed: bool
    local_date: date


class RoutineStepOut(BaseModel):
    id: str
    title: str
    position: int
    archived: bool
    completed: bool


class RoutineOut(RoutineSchedule):
    id: str
    archived: bool
    local_date: date
    scheduled_today: bool
    window_state: str
    steps: list[RoutineStepOut]


class CompletionOut(BaseModel):
    step_id: str
    title: str
    local_date: date
    completed_at: datetime


def local_now(user: User):
    return datetime.now(timezone.utc).astimezone(ZoneInfo(user.timezone_name))


def owned_routine(db: Session, owner_id: str, routine_id: str, lock: bool = False):
    stmt = select(Routine).where(Routine.owner_id == owner_id, Routine.id == routine_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(404, "Routine nicht gefunden")
    return row


def routine_output(db: Session, row: Routine, current: datetime, include_archived_steps: bool = False):
    day = current.date()
    stmt = select(RoutineStep).where(RoutineStep.routine_id == row.id)
    if not include_archived_steps:
        stmt = stmt.where(RoutineStep.archived.is_(False))
    steps = list(db.scalars(stmt.order_by(RoutineStep.position)))
    completed = set(db.scalars(select(RoutineCompletion.step_id).where(RoutineCompletion.step_id.in_([s.id for s in steps]), RoutineCompletion.local_date == day)))
    scheduled = not row.archived and day.weekday() in row.weekdays
    state = "not_scheduled"
    if scheduled:
        clock = current.time().replace(tzinfo=None)
        state = "anytime" if row.window_start is None else "upcoming" if clock < row.window_start else "past" if clock >= row.window_end else "active"
    return RoutineOut(id=row.id, title=row.title, weekdays=row.weekdays, window_start=row.window_start, window_end=row.window_end, archived=row.archived, local_date=day, scheduled_today=scheduled, window_state=state, steps=[RoutineStepOut(id=s.id, title=s.title, position=s.position, archived=s.archived, completed=s.id in completed) for s in steps])


def list_routines(db: Session, user: User, today_only: bool = False, include_archived: bool = False):
    current = local_now(user)
    stmt = select(Routine).where(Routine.owner_id == user.id)
    if not include_archived or today_only:
        stmt = stmt.where(Routine.archived.is_(False))
    rows = list(db.scalars(stmt.order_by(Routine.window_start.is_(None), Routine.window_start, Routine.title, Routine.id)))
    return [routine_output(db, row, current, include_archived_steps=not today_only) for row in rows if not today_only or current.weekday() in row.weekdays]


def audit(db, owner, action, resource_type, resource_id, source):
    db.add(AuditEvent(owner_id=owner, action=action, resource_type=resource_type, resource_id=resource_id, source=source))


def create_routine(db: Session, user: User, data: RoutineCreate, source: str = "rest"):
    # Serialize the account's template limit on PostgreSQL.
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    count = len(list(db.scalars(select(Routine.id).where(Routine.owner_id == user.id).limit(100))))
    if count >= 100:
        raise HTTPException(422, "Maximal 100 Routinen pro Konto")
    row = Routine(owner_id=user.id, **data.model_dump(exclude={"steps"}))
    db.add(row)
    db.flush()
    db.add_all(RoutineStep(routine_id=row.id, position=i, title=step.title) for i, step in enumerate(data.steps, 1))
    audit(db, user.id, "create", "routines", row.id, source)
    db.commit()
    return routine_output(db, row, local_now(user), True)


def update_routine(db: Session, user: User, routine_id: str, data: RoutineSchedule, source: str = "rest"):
    row = owned_routine(db, user.id, routine_id, True)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    audit(db, user.id, "update", "routines", row.id, source)
    db.commit()
    return routine_output(db, row, local_now(user), True)


def archive_routine(db: Session, user: User, routine_id: str, data: ArchiveIn, source: str = "rest"):
    row = owned_routine(db, user.id, routine_id, True)
    if row.archived != data.archived:
        row.archived = data.archived
        audit(db, user.id, "update", "routines", row.id, source)
        db.commit()
    return routine_output(db, row, local_now(user), True)


def add_step(db: Session, user: User, routine_id: str, data: RoutineStepIn, source: str = "rest"):
    row = owned_routine(db, user.id, routine_id, True)
    steps = list(db.scalars(select(RoutineStep).where(RoutineStep.routine_id == row.id)))
    if row.archived or len(steps) >= 100:
        raise HTTPException(409, "Archivierte Routine oder Schrittlimit erreicht")
    step = RoutineStep(routine_id=row.id, title=data.title, position=max((s.position for s in steps), default=0) + 1)
    db.add(step)
    db.flush()
    audit(db, user.id, "create", "routine_steps", step.id, source)
    db.commit()
    return routine_output(db, row, local_now(user), True)


def owned_step(db: Session, routine_id: str, step_id: str):
    step = db.scalar(select(RoutineStep).where(RoutineStep.routine_id == routine_id, RoutineStep.id == step_id))
    if step is None:
        raise HTTPException(404, "Routinenschritt nicht gefunden")
    return step


def archive_step(db: Session, user: User, routine_id: str, step_id: str, data: ArchiveIn, source: str = "rest"):
    row = owned_routine(db, user.id, routine_id, True)
    step = owned_step(db, row.id, step_id)
    if step.archived != data.archived:
        if data.archived and db.scalar(select(RoutineStep.id).where(RoutineStep.routine_id == row.id, RoutineStep.id != step.id, RoutineStep.archived.is_(False)).limit(1)) is None:
            raise HTTPException(409, "Mindestens ein aktiver Schritt muss erhalten bleiben")
        step.archived = data.archived
        audit(db, user.id, "update", "routine_steps", step.id, source)
        db.commit()
    return routine_output(db, row, local_now(user), True)


def set_completion(db: Session, user: User, routine_id: str, step_id: str, data: CompletionIn, source: str = "rest"):
    row = owned_routine(db, user.id, routine_id, True)
    step = owned_step(db, row.id, step_id)
    current = local_now(user)
    if data.local_date != current.date():
        raise HTTPException(409, "Kalendertag hat sich geändert. Bitte aktualisieren.")
    if row.archived or step.archived or current.weekday() not in row.weekdays:
        raise HTTPException(409, "Routine oder Schritt ist heute nicht aktiv")
    existing = db.scalar(select(RoutineCompletion).where(RoutineCompletion.step_id == step.id, RoutineCompletion.local_date == current.date()))
    if data.completed and existing is None:
        existing = RoutineCompletion(step_id=step.id, local_date=current.date())
        db.add(existing)
        db.flush()
        audit(db, user.id, "create", "routine_completions", existing.id, source)
        db.commit()
    elif not data.completed and existing is not None:
        audit(db, user.id, "delete", "routine_completions", existing.id, source)
        db.delete(existing)
        db.commit()
    return routine_output(db, row, current, True)


def routine_history(db: Session, user: User, routine_id: str, days: int = 30):
    row = owned_routine(db, user.id, routine_id)
    today = local_now(user).date()
    items = db.execute(select(RoutineCompletion, RoutineStep.title).join(RoutineStep, RoutineCompletion.step_id == RoutineStep.id).where(RoutineStep.routine_id == row.id, RoutineCompletion.local_date >= today - timedelta(days=days-1), RoutineCompletion.local_date <= today).order_by(RoutineCompletion.local_date.desc(), RoutineStep.position)).all()
    return [CompletionOut(step_id=c.step_id, title=title, local_date=c.local_date, completed_at=c.completed_at.replace(tzinfo=timezone.utc) if c.completed_at.tzinfo is None else c.completed_at) for c,title in items]


@router.get("", response_model=list[RoutineOut])
def get_routines(today_only: bool = False, include_archived: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return list_routines(db, user, today_only, include_archived)


@router.post("", response_model=RoutineOut, status_code=201)
def post_routine(data: RoutineCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return create_routine(db, user, data)


@router.put("/{routine_id}", response_model=RoutineOut)
def put_routine(routine_id: str, data: RoutineSchedule, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return update_routine(db, user, routine_id, data)


@router.patch("/{routine_id}/archive", response_model=RoutineOut)
def patch_routine_archive(routine_id: str, data: ArchiveIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return archive_routine(db, user, routine_id, data)


@router.post("/{routine_id}/steps", response_model=RoutineOut, status_code=201)
def post_step(routine_id: str, data: RoutineStepIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return add_step(db, user, routine_id, data)


@router.patch("/{routine_id}/steps/{step_id}/archive", response_model=RoutineOut)
def patch_step_archive(routine_id: str, step_id: str, data: ArchiveIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return archive_step(db, user, routine_id, step_id, data)


@router.patch("/{routine_id}/steps/{step_id}/completion", response_model=RoutineOut)
def patch_completion(routine_id: str, step_id: str, data: CompletionIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return set_completion(db, user, routine_id, step_id, data)


@router.get("/{routine_id}/history", response_model=list[CompletionOut])
def get_history(routine_id: str, days: int = Query(30, ge=1, le=90), db: Session = Depends(get_db), user: User = Depends(current_user)):
    return routine_history(db, user, routine_id, days)
