import json
from datetime import datetime
from typing import TypedDict

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lifepilot.models import Conversation, ConversationParticipant, ConversationProject, ResourceRevision, Task


class RevisionSnapshot(TypedDict):
    id: str
    fields: dict[str, str | int | None | list[str]]


class RevisionView(TypedDict):
    id: str
    resource_type: str
    resource_id: str
    revision: int
    action: str
    source: str
    snapshot: RevisionSnapshot
    created_at: datetime


def _store_revision(db: Session, owner_id: str, resource_type: str, resource_id: str, fields: dict[str, str | int | None | list[str]], action: str, source: str) -> None:
    latest = db.scalar(select(func.max(ResourceRevision.revision)).where(ResourceRevision.owner_id == owner_id, ResourceRevision.resource_type == resource_type, ResourceRevision.resource_id == resource_id))
    db.add(ResourceRevision(owner_id=owner_id, resource_type=resource_type, resource_id=resource_id, revision=(latest or 0) + 1, action=action, source=source, snapshot_json=json.dumps({"id": resource_id, "fields": fields}, ensure_ascii=False)))


def record_task_revision(db: Session, task: Task, action: str, source: str) -> None:
    _store_revision(db, task.owner_id, "task", task.id, {
        "title": task.title,
        "description": task.description,
        "person_id": task.person_id,
        "project_id": task.project_id,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "priority": task.priority,
        "estimated_minutes": task.estimated_minutes,
        "mental_effort": task.mental_effort,
        "start_friction": task.start_friction,
        "work_context": task.work_context,
        "next_step": task.next_step,
        "status": task.status,
        "repeat_interval_days": task.repeat_interval_days,
        "repeat_until": task.repeat_until.isoformat() if task.repeat_until else None,
    }, action, source)


def record_conversation_revision(db: Session, conversation: Conversation, action: str, source: str) -> None:
    db.flush()
    participant_ids = list(db.scalars(select(ConversationParticipant.person_id).where(ConversationParticipant.conversation_id == conversation.id, ConversationParticipant.owner_id == conversation.owner_id)).all())
    project_ids = list(db.scalars(select(ConversationProject.project_id).where(ConversationProject.conversation_id == conversation.id, ConversationProject.owner_id == conversation.owner_id)).all())
    _store_revision(db, conversation.owner_id, "conversation", conversation.id, {
        "title": conversation.title,
        "original_note": conversation.original_note,
        "summary": conversation.summary,
        "location": conversation.location,
        "occurred_at": conversation.occurred_at.isoformat() if conversation.occurred_at else None,
        "participant_ids": sorted(participant_ids),
        "project_ids": sorted(project_ids),
    }, action, source)


def history(db: Session, owner_id: str, resource_type: str, resource_id: str) -> list[RevisionView]:
    model = {"task": Task, "conversation": Conversation}.get(resource_type)
    if model is None or db.scalar(select(model.id).where(model.id == resource_id, model.owner_id == owner_id)) is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    rows = db.scalars(select(ResourceRevision).where(ResourceRevision.owner_id == owner_id, ResourceRevision.resource_type == resource_type, ResourceRevision.resource_id == resource_id).order_by(ResourceRevision.revision.desc())).all()
    return [{"id": row.id, "resource_type": row.resource_type, "resource_id": row.resource_id, "revision": row.revision, "action": row.action, "source": row.source, "snapshot": json.loads(row.snapshot_json), "created_at": row.created_at} for row in rows]
