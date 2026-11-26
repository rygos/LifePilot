from datetime import datetime, timezone, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.models import Task, User
from lifepilot.revisions import record_task_revision
from lifepilot.security import current_user
from lifepilot.schemas import TaskOut

router = APIRouter(prefix="/api", tags=["Intelligente Planung"])
Effort = Literal["low", "medium", "high"]
Context = Literal["computer", "phone", "home", "outside", "any"]
LEVEL = {"low": 1, "medium": 2, "high": 3}


class TaskPlanning(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estimated_minutes: int | None = Field(default=None, ge=1, le=1440)
    mental_effort: Effort | None = None
    start_friction: Effort | None = None
    work_context: Context | None = None
    next_step: str | None = Field(default=None, max_length=5000)


class Recommendation(BaseModel):
    task: TaskOut
    reason: str


class NextActions(BaseModel):
    recommended: list[Recommendation]
    needs_details: list[TaskOut]


def set_planning(db: Session, owner: str, task_id: str, data: TaskPlanning, source: str = "rest"):
    task = db.scalar(select(Task).where(Task.id == task_id, Task.owner_id == owner).with_for_update())
    if task is None:
        raise HTTPException(404, "Aufgabe nicht gefunden")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(task, key, value.strip() or None if isinstance(value, str) else value)
    record_task_revision(db, task, "updated", source)
    db.commit()
    db.refresh(task)
    return task


def next_actions(db: Session, owner: str, minutes: int, energy: Effort, context: Context) -> NextActions:
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(Task).where(Task.owner_id == owner, Task.status == "open")).all()
    matches = []
    incomplete = []
    for task in rows:
        if task.estimated_minutes is not None and task.estimated_minutes > minutes:
            continue
        if task.mental_effort is not None and LEVEL.get(task.mental_effort, 4) > LEVEL[energy]:
            continue
        if task.work_context not in (None, "any") and context != "any" and task.work_context != context:
            continue
        if task.estimated_minutes is None or task.mental_effort is None or task.work_context is None:
            incomplete.append(task)
            continue
        due = task.due_at
        if due is not None and due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        urgency = 2 if due and due <= now else 1 if due and due <= now + timedelta(days=1) else 0
        friction = LEVEL.get(task.start_friction, 2)
        reason = f"{task.estimated_minutes} Min. · Aufwand und Kontext passen"
        if urgency == 2:
            reason += " · Überfällig"
        elif urgency == 1:
            reason += " · Bald fällig"
        key = (-urgency, friction, due or datetime.max.replace(tzinfo=timezone.utc), task.estimated_minutes, task.id)
        matches.append((key, Recommendation(task=TaskOut.model_validate(task), reason=reason)))
    matches.sort(key=lambda x: x[0])
    incomplete.sort(key=lambda t: (t.title.casefold(), t.id))
    return NextActions(recommended=[r for _, r in matches[:3]], needs_details=[TaskOut.model_validate(t) for t in incomplete[:10]])


@router.patch("/tasks/{task_id}/planning", response_model=TaskOut)
def planning_update(task_id: str, data: TaskPlanning, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return set_planning(db, user.id, task_id, data)


@router.get("/planning/next-actions", response_model=NextActions)
def recommendations(minutes: int = Query(15, ge=1, le=1440), energy: Effort = "medium", context: Context = "any", db: Session = Depends(get_db), user: User = Depends(current_user)):
    return next_actions(db, user.id, minutes, energy, context)
