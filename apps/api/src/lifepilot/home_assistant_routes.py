"""Minimal, opt-in status endpoint for Home Assistant REST sensors."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.models import FocusSession
from lifepilot.push_worker import due_keys
from lifepilot.routine_routes import list_routines
from lifepilot.services import is_quiet_hours
from lifepilot import shortcut_routes

router = APIRouter(prefix="/api/home-assistant", tags=["Home Assistant"])


class HomeStatus(BaseModel):
    notification_pending: bool
    quiet_hours: bool
    due_reminders: int
    due_commitments: int
    due_routines: int
    routine_steps_open: int
    focus_active: bool


@router.get("/status", response_model=HomeStatus)
def home_status(response: Response, credentials: HTTPAuthorizationCredentials | None = Depends(shortcut_routes.bearer), db: Session = Depends(get_db)):
    owner = shortcut_routes.integration_user(credentials, db, "ha:status", shortcut_routes.STATUS_REQUESTS_PER_HOUR)
    now = datetime.now(timezone.utc)
    quiet = is_quiet_hours(owner, now)
    keys = due_keys(db, owner, now)
    routines = list_routines(db, owner, today_only=True)
    active_focus = db.scalar(select(FocusSession.id).where(FocusSession.owner_id == owner.id, FocusSession.ended_at.is_(None)).limit(1)) is not None
    response.headers["Cache-Control"] = "no-store"
    return HomeStatus(
        notification_pending=bool(keys) and not quiet,
        quiet_hours=quiet,
        due_reminders=sum(k.startswith("reminder:") for k in keys),
        due_commitments=sum(k.startswith("commitment:") for k in keys),
        due_routines=sum(k.startswith("routine:") for k in keys),
        routine_steps_open=sum(not step.completed for routine in routines for step in routine.steps),
        focus_active=active_focus,
    )
