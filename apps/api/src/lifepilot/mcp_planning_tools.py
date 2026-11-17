from datetime import datetime
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from mcp.server.fastmcp import FastMCP

from lifepilot.main import person_delete, relationship_delete
from lifepilot.models import AuditEvent, Conversation, ConversationParticipant, Gift, Loan, Person, Reminder, Task, User
from lifepilot.planner import event_update, reminder_create, reminder_update
from lifepilot.schemas import ConversationOut, EventPatch, GiftOut, LoanOut, ReminderAction, ReminderIn, ReminderOut, TaskIn, TaskOut
from lifepilot.services import owned_person
from lifepilot.mcp_tools import mcp_session, mcp_user


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value is not None else None


def register_planning_tools(mcp: FastMCP) -> None:
    @mcp.tool(name="task_update")
    def task_update_mcp(task_id: str, title: str | None = None, description: str | None = None, person_id: str | None = None, due_at: str | None = None, priority: int | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Task).where(Task.id == task_id, Task.owner_id == owner_id))
            if row is None: raise ValueError("Aufgabe nicht gefunden")
            if person_id is not None: owned_person(db, person_id, db.get(User, owner_id))
            candidate = TaskIn(title=title or row.title, description=description if description is not None else row.description, person_id=person_id if person_id is not None else row.person_id, due_at=_parse_datetime(due_at) if due_at is not None else row.due_at, priority=priority if priority is not None else row.priority, repeat_interval_days=row.repeat_interval_days, repeat_until=row.repeat_until)
            for field in ("title", "description", "person_id", "due_at", "priority", "repeat_interval_days", "repeat_until"):
                setattr(row, field, getattr(candidate, field))
            db.commit(); db.refresh(row)
            return TaskOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="event_update")
    def event_update_mcp(event_id: str, title: str | None = None, description: str | None = None, location: str | None = None, starts_at: str | None = None, ends_at: str | None = None, participant_ids: list[str] | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        changes = {key: value for key, value in (("title", title), ("description", description), ("location", location), ("starts_at", _parse_datetime(starts_at)), ("ends_at", _parse_datetime(ends_at)), ("participant_ids", participant_ids)) if value is not None}
        with mcp_session(owner_id) as db:
            return event_update(event_id, EventPatch.model_validate(changes), db, db.get(User, owner_id)).model_dump(mode="json")

    @mcp.tool(name="conversation_get")
    def conversation_get_mcp(conversation_id: str) -> dict:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.owner_id == owner_id))
            if row is None: raise ValueError("Gespräch nicht gefunden")
            participants = list(db.scalars(select(ConversationParticipant.person_id).where(ConversationParticipant.conversation_id == row.id, ConversationParticipant.owner_id == owner_id)).all())
            return ConversationOut(id=row.id, title=row.title, original_note=row.original_note, summary=row.summary, location=row.location, occurred_at=row.occurred_at, created_at=row.created_at, participant_ids=participants).model_dump(mode="json")

    @mcp.tool(name="conversation_update")
    def conversation_update_mcp(conversation_id: str, title: str | None = None, original_note: str | None = None, summary: str | None = None, location: str | None = None, occurred_at: str | None = None, participant_ids: list[str] | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.owner_id == owner_id))
            if row is None: raise ValueError("Gespräch nicht gefunden")
            for key, value in (("title", title), ("original_note", original_note), ("summary", summary), ("location", location), ("occurred_at", _parse_datetime(occurred_at))):
                if value is not None: setattr(row, key, value)
            if participant_ids is not None:
                ids = set(participant_ids)
                valid = set(db.scalars(select(Person.id).where(Person.owner_id == owner_id, Person.id.in_(ids))).all()) if ids else set()
                if ids != valid: raise ValueError("Mindestens eine beteiligte Person wurde nicht gefunden")
                db.execute(delete(ConversationParticipant).where(ConversationParticipant.conversation_id == row.id, ConversationParticipant.owner_id == owner_id))
                db.add_all(ConversationParticipant(conversation_id=row.id, person_id=person_id, owner_id=owner_id) for person_id in ids)
            db.commit(); db.refresh(row)
            participants = list(db.scalars(select(ConversationParticipant.person_id).where(ConversationParticipant.conversation_id == row.id, ConversationParticipant.owner_id == owner_id)).all())
            return ConversationOut(id=row.id, title=row.title, original_note=row.original_note, summary=row.summary, location=row.location, occurred_at=row.occurred_at, created_at=row.created_at, participant_ids=participants).model_dump(mode="json")

    @mcp.tool(name="reminder_create")
    def reminder_create_mcp(due_at: str, task_id: str | None = None, event_id: str | None = None, title: str = "") -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            reminder = reminder_create(ReminderIn(title=title or "Erinnerung", due_at=_parse_datetime(due_at), task_id=task_id, event_id=event_id), db, db.get(User, owner_id))
            return ReminderOut.model_validate(reminder).model_dump(mode="json")

    @mcp.tool(name="reminder_update")
    def reminder_update_mcp(reminder_id: str, state: Literal["scheduled", "done", "muted"], snoozed_until: str | None = None) -> dict:
        from lifepilot.main import User
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            reminder = reminder_update(reminder_id, ReminderAction(state=state, snoozed_until=_parse_datetime(snoozed_until)), db, db.get(User, owner_id))
            return ReminderOut.model_validate(reminder).model_dump(mode="json")

    @mcp.tool(name="person_delete")
    def person_delete_mcp(person_id: str, confirm: bool) -> dict:
        if not confirm: raise ValueError("Löschen erfordert confirm=true")
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            person_delete(person_id, db, db.get(User, owner_id))
            return {"deleted": True, "person_id": person_id}

    @mcp.tool(name="relationship_delete")
    def relationship_delete_mcp(relationship_id: str, confirm: bool) -> dict:
        if not confirm: raise ValueError("Löschen erfordert confirm=true")
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            relationship_delete(relationship_id, db, db.get(User, owner_id))
            return {"deleted": True, "relationship_id": relationship_id}

    @mcp.tool(name="loan_update")
    def loan_update_mcp(loan_id: str, item_name: str | None = None, due_at: str | None = None, condition_note: str | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Loan).where(Loan.id == loan_id, Loan.owner_id == owner_id))
            if row is None: raise ValueError("Leihgabe nicht gefunden")
            if item_name is not None: row.item_name = item_name
            if due_at is not None: row.due_at = _parse_datetime(due_at)
            if condition_note is not None: row.condition_note = condition_note
            db.commit(); db.refresh(row)
            return LoanOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="gift_update")
    def gift_update_mcp(gift_id: str, title: str | None = None, note: str | None = None, occasion: str | None = None, budget: int | None = None, status: str | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Gift).where(Gift.id == gift_id, Gift.owner_id == owner_id))
            if row is None: raise ValueError("Geschenkidee nicht gefunden")
            for key, value in (("title", title), ("note", note), ("occasion", occasion), ("budget", budget), ("status", status)):
                if value is not None: setattr(row, key, value)
            db.commit(); db.refresh(row)
            return GiftOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="audit_search")
    def audit_search_mcp(limit: int = 50) -> list[dict]:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            rows = db.scalars(select(AuditEvent).where(AuditEvent.owner_id == owner_id).order_by(AuditEvent.created_at.desc()).limit(max(1, min(limit, 200)))).all()
            return [{"id": row.id, "action": row.action, "resource_type": row.resource_type, "resource_id": row.resource_id, "source": row.source, "created_at": row.created_at.isoformat()} for row in rows]
