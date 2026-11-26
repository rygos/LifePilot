from datetime import datetime
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from mcp.server.fastmcp import FastMCP

from lifepilot.approval_policy import active_filters
from lifepilot.models import ApprovalRequest, AuditEvent, Conversation, ConversationParticipant, ConversationProject, Gift, Loan, Person, Project, Relationship, Reminder, Task, User
from lifepilot.entity_embedding_jobs import enqueue_entity_embedding
from lifepilot.planner import event_update, reminder_create, reminder_update
from lifepilot.schemas import ConversationOut, EventPatch, GiftOut, LoanOut, ProjectIn, ProjectOut, ProjectPatch, ReminderAction, ReminderIn, ReminderOut, TaskIn, TaskOut
from lifepilot.services import owned_person, project_create, project_get, project_list, project_update
from lifepilot.mcp_tools import mcp_session, mcp_user, request_approval
from lifepilot.revisions import history, record_conversation_revision, record_task_revision


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value is not None else None


def register_planning_tools(mcp: FastMCP) -> None:
    @mcp.tool(name="project_create")
    def project_create_mcp(name: str, description: str = "", status: Literal["active", "paused", "completed", "archived"] = "active") -> dict:
        owner_id = mcp_user("projects:write")
        with mcp_session(owner_id) as db:
            row = project_create(db, db.get(User, owner_id), ProjectIn(name=name, description=description, status=status))
            return ProjectOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="project_search")
    def project_search_mcp(query: str = "", status: Literal["active", "paused", "completed", "archived"] | None = None) -> list[dict]:
        owner_id = mcp_user("projects:read")
        with mcp_session(owner_id) as db:
            return [ProjectOut.model_validate(row).model_dump(mode="json") for row in project_list(db, db.get(User, owner_id), query, status)]

    @mcp.tool(name="project_get")
    def project_get_mcp(project_id: str) -> dict:
        owner_id = mcp_user("projects:read")
        with mcp_session(owner_id) as db:
            return ProjectOut.model_validate(project_get(db, db.get(User, owner_id), project_id)).model_dump(mode="json")

    @mcp.tool(name="project_update")
    def project_update_mcp(project_id: str, name: str | None = None, description: str | None = None, status: Literal["active", "paused", "completed", "archived"] | None = None) -> dict:
        owner_id = mcp_user("projects:write")
        with mcp_session(owner_id) as db:
            row = project_update(db, db.get(User, owner_id), project_id, ProjectPatch(name=name, description=description, status=status))
            return ProjectOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="project_delete")
    def project_delete_mcp(project_id: str) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Project).where(Project.id == project_id, Project.owner_id == owner_id))
            if row is None: raise ValueError("Projekt nicht gefunden")
            return request_approval(db, owner_id, "project_delete", row.id, row.name)

    @mcp.tool(name="approval_search")
    def approval_search_mcp() -> list[dict]:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            rows = db.scalars(select(ApprovalRequest).where(*active_filters(owner_id)).order_by(ApprovalRequest.created_at)).all()
            return [{"id": row.id, "operation": row.operation, "resource_id": row.resource_id, "resource_label": row.resource_label, "status": row.status, "created_at": row.created_at.isoformat()} for row in rows]
    @mcp.tool(name="task_update")
    def task_update_mcp(task_id: str, title: str | None = None, description: str | None = None, person_id: str | None = None, project_id: str | None = None, due_at: str | None = None, priority: int | None = None) -> dict:
        owner_id = mcp_user("tasks:write")
        if person_id:
            mcp_user("people:read")
        if project_id:
            mcp_user("projects:read")
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Task).where(Task.id == task_id, Task.owner_id == owner_id))
            if row is None: raise ValueError("Aufgabe nicht gefunden")
            if person_id is not None: owned_person(db, person_id, db.get(User, owner_id))
            if project_id is not None and db.scalar(select(Project.id).where(Project.id == project_id, Project.owner_id == owner_id)) is None: raise ValueError("Projekt nicht gefunden")
            candidate = TaskIn(title=title or row.title, description=description if description is not None else row.description, person_id=person_id if person_id is not None else row.person_id, project_id=project_id if project_id is not None else row.project_id, due_at=_parse_datetime(due_at) if due_at is not None else row.due_at, priority=priority if priority is not None else row.priority, repeat_interval_days=row.repeat_interval_days, repeat_until=row.repeat_until)
            for field in ("title", "description", "person_id", "project_id", "due_at", "priority", "repeat_interval_days", "repeat_until"):
                setattr(row, field, getattr(candidate, field))
            record_task_revision(db, row, "updated", "mcp")
            db.commit(); db.refresh(row)
            enqueue_entity_embedding("task", row.id, owner_id)
            return TaskOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="event_update")
    def event_update_mcp(event_id: str, title: str | None = None, record_type: str | None = None, description: str | None = None, location: str | None = None, location_address: str | None = None, starts_at: str | None = None, ends_at: str | None = None, participant_ids: list[str] | None = None) -> dict:
        owner_id = mcp_user("calendar:write")
        if participant_ids is not None:
            mcp_user("people:read")
        changes = {key: value for key, value in (("title", title), ("record_type", record_type), ("description", description), ("location", location), ("location_address", location_address), ("starts_at", _parse_datetime(starts_at)), ("ends_at", _parse_datetime(ends_at)), ("participant_ids", participant_ids)) if value is not None}
        with mcp_session(owner_id) as db:
            return event_update(event_id, EventPatch.model_validate(changes), db, db.get(User, owner_id)).model_dump(mode="json")

    @mcp.tool(name="conversation_get")
    def conversation_get_mcp(conversation_id: str) -> dict:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.owner_id == owner_id))
            if row is None: raise ValueError("Gespräch nicht gefunden")
            participants = list(db.scalars(select(ConversationParticipant.person_id).where(ConversationParticipant.conversation_id == row.id, ConversationParticipant.owner_id == owner_id)).all())
            project_ids = list(db.scalars(select(ConversationProject.project_id).where(ConversationProject.conversation_id == row.id, ConversationProject.owner_id == owner_id)).all())
            return ConversationOut(id=row.id, title=row.title, original_note=row.original_note, summary=row.summary, location=row.location, occurred_at=row.occurred_at, created_at=row.created_at, participant_ids=participants, project_ids=project_ids).model_dump(mode="json")

    @mcp.tool(name="task_history")
    def task_history_mcp(task_id: str) -> list[dict]:
        owner_id = mcp_user("tasks:read")
        with mcp_session(owner_id) as db:
            return history(db, owner_id, "task", task_id)

    @mcp.tool(name="conversation_history")
    def conversation_history_mcp(conversation_id: str) -> list[dict]:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            return history(db, owner_id, "conversation", conversation_id)

    @mcp.tool(name="conversation_update")
    def conversation_update_mcp(conversation_id: str, title: str | None = None, original_note: str | None = None, summary: str | None = None, location: str | None = None, occurred_at: str | None = None, participant_ids: list[str] | None = None, project_ids: list[str] | None = None) -> dict:
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
            if project_ids is not None:
                ids = set(project_ids)
                valid = set(db.scalars(select(Project.id).where(Project.owner_id == owner_id, Project.id.in_(ids))).all()) if ids else set()
                if ids != valid: raise ValueError("Mindestens ein verknüpftes Projekt wurde nicht gefunden")
                db.execute(delete(ConversationProject).where(ConversationProject.conversation_id == row.id, ConversationProject.owner_id == owner_id))
                db.add_all(ConversationProject(conversation_id=row.id, project_id=project_id, owner_id=owner_id) for project_id in ids)
            record_conversation_revision(db, row, "updated", "mcp")
            db.commit(); db.refresh(row)
            enqueue_entity_embedding("conversation", row.id, owner_id)
            participants = list(db.scalars(select(ConversationParticipant.person_id).where(ConversationParticipant.conversation_id == row.id, ConversationParticipant.owner_id == owner_id)).all())
            project_ids = list(db.scalars(select(ConversationProject.project_id).where(ConversationProject.conversation_id == row.id, ConversationProject.owner_id == owner_id)).all())
            return ConversationOut(id=row.id, title=row.title, original_note=row.original_note, summary=row.summary, location=row.location, occurred_at=row.occurred_at, created_at=row.created_at, participant_ids=participants, project_ids=project_ids).model_dump(mode="json")

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
    def person_delete_mcp(person_id: str) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            person = db.scalar(select(Person).where(Person.id == person_id, Person.owner_id == owner_id))
            if person is None: raise ValueError("Person nicht gefunden")
            return request_approval(db, owner_id, "person_delete", person.id, f"{person.first_name} {person.last_name}".strip())

    @mcp.tool(name="relationship_delete")
    def relationship_delete_mcp(relationship_id: str) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            relationship = db.scalar(select(Relationship).where(Relationship.id == relationship_id, Relationship.owner_id == owner_id))
            if relationship is None: raise ValueError("Beziehung nicht gefunden")
            source = db.scalar(select(Person).where(Person.id == relationship.source_person_id, Person.owner_id == owner_id))
            target = db.scalar(select(Person).where(Person.id == relationship.target_person_id, Person.owner_id == owner_id))
            source_name = f"{source.first_name} {source.last_name}".strip() if source else "Person"
            target_name = f"{target.first_name} {target.last_name}".strip() if target else "Person"
            label = f"{source_name} · {relationship.relationship_type} · {target_name}"
            return request_approval(db, owner_id, "relationship_delete", relationship.id, label)

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
