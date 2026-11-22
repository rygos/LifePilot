from datetime import datetime
from typing import Literal

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from lifepilot.capture_routes import capture_create, capture_output, capture_review
from lifepilot.capture_schemas import CaptureIn, CaptureReviewIn, CaptureSuggestion
from lifepilot.entity_embedding_jobs import delete_entity_embedding, enqueue_person_context_embeddings
from lifepilot.embedding_jobs import enqueue_memory_embedding
from lifepilot.main import profile_update
from lifepilot.models import (
    AuditEvent,
    Attachment,
    Attachment,
    Capture,
    Conversation,
    ConversationParticipant,
    Event,
    EventParticipant,
    Gift,
    Loan,
    Memory,
    Person,
    Relationship,
    Reminder,
    Task,
    User,
    UserPersonRelationship,
)
from lifepilot.schemas import MemoryOut, ProfileUpdate, ReminderOut
from lifepilot.services import owned_person
from lifepilot.mcp_tools import mcp_session, mcp_user


def _request_delete(owner_id: str, model: type, resource_id: str, operation: str) -> dict:
    from lifepilot.mcp_tools import request_approval

    with mcp_session(owner_id) as db:
        row = db.scalar(select(model).where(model.id == resource_id, model.owner_id == owner_id))
        if row is None:
            raise ValueError("Eintrag nicht gefunden")
        label = getattr(row, "title", getattr(row, "name", getattr(row, "item_name", "Eintrag")))
        return request_approval(db, owner_id, operation, row.id, label)


def register_extended_tools(mcp: FastMCP) -> None:
    @mcp.tool(name="attachment_search")
    def attachment_search_mcp(resource_type: Literal["person", "memory", "conversation", "event"], resource_id: str) -> list[dict]:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            model_by_type = {"person": Person, "memory": Memory, "conversation": Conversation, "event": Event}
            model = model_by_type[resource_type]
            exists = db.scalar(select(model.id).where(model.id == resource_id, model.owner_id == owner_id))
            if exists is None:
                raise ValueError("Zugehöriger Eintrag nicht gefunden")
            rows = db.scalars(
                select(Attachment)
                .where(
                    Attachment.owner_id == owner_id,
                    Attachment.resource_type == resource_type,
                    Attachment.resource_id == resource_id,
                )
                .order_by(Attachment.created_at, Attachment.id)
            ).all()
            return [
                {
                    "id": row.id,
                    "resource_type": row.resource_type,
                    "resource_id": row.resource_id,
                    "file_name": row.file_name,
                    "content_type": row.content_type,
                    "size_bytes": row.size_bytes,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    @mcp.tool(name="attachment_search")
    def attachment_search_mcp(resource_type: str, resource_id: str) -> list[dict]:
        """Listet Metadaten privater Dateien eines eigenen Eintrags auf."""
        if resource_type not in {"person", "memory", "conversation", "event"}:
            raise ValueError("Nicht unterstützter Eintragstyp")
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            model_by_type = {"person": Person, "memory": Memory, "conversation": Conversation, "event": Event}
            model = model_by_type[resource_type]
            exists = db.scalar(select(model.id).where(model.id == resource_id, model.owner_id == owner_id))
            if exists is None:
                raise ValueError("Zugehöriger Eintrag nicht gefunden")
            rows = db.scalars(
                select(Attachment)
                .where(
                    Attachment.owner_id == owner_id,
                    Attachment.resource_type == resource_type,
                    Attachment.resource_id == resource_id,
                )
                .order_by(Attachment.created_at, Attachment.id)
            ).all()
            return [
                {
                    "id": row.id,
                    "resource_type": row.resource_type,
                    "resource_id": row.resource_id,
                    "file_name": row.file_name,
                    "content_type": row.content_type,
                    "size_bytes": row.size_bytes,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    @mcp.tool(name="memory_capture")
    def memory_capture_mcp(original_text: str) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            result = capture_create(CaptureIn(original_text=original_text), db, db.get(User, owner_id))
            return result.model_dump(mode="json")

    @mcp.tool(name="memory_capture_status")
    def memory_capture_status_mcp(capture_id: str) -> dict:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Capture).where(Capture.id == capture_id, Capture.owner_id == owner_id))
            if row is None:
                raise ValueError("Eingabe nicht gefunden")
            return capture_output(row).model_dump(mode="json")

    @mcp.tool(name="memory_capture_list")
    def memory_capture_list_mcp(limit: int = 20) -> list[dict]:
        if limit < 1 or limit > 100:
            raise ValueError("Die Anzahl muss zwischen 1 und 100 liegen")
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            rows = db.scalars(select(Capture).where(Capture.owner_id == owner_id).order_by(Capture.created_at.desc()).limit(limit)).all()
            return [capture_output(row).model_dump(mode="json") for row in rows]

    @mcp.tool(name="profile_get")
    def profile_get_mcp() -> dict:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            user = db.get(User, owner_id)
            return {
                "username": user.username,
                "full_name": user.full_name,
                "nickname": user.nickname,
                "birthday": user.birthday,
                "email": user.email,
                "phone": user.phone,
                "address": user.address,
                "timezone_name": user.timezone_name,
                "quiet_hours_start": user.quiet_hours_start.isoformat() if user.quiet_hours_start else None,
                "quiet_hours_end": user.quiet_hours_end.isoformat() if user.quiet_hours_end else None,
            }

    @mcp.tool(name="profile_update")
    def profile_update_mcp(
        full_name: str | None = None,
        nickname: str | None = None,
        birthday: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        address: str | None = None,
        timezone_name: str | None = None,
        quiet_hours_start: str | None = None,
        quiet_hours_end: str | None = None,
    ) -> dict:
        owner_id = mcp_user("memory:write")
        changes = {
            key: value
            for key, value in locals().copy().items()
            if key in ProfileUpdate.model_fields and value is not None
        }
        with mcp_session(owner_id) as db:
            return profile_update(ProfileUpdate.model_validate(changes), db, db.get(User, owner_id)).model_dump(mode="json")

    @mcp.tool(name="note_create")
    def note_create_mcp(title: str, content: str, person_id: str | None = None, occurred_at: str | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            owner = db.get(User, owner_id)
            owned_person(db, person_id, owner)
            row = Memory(
                owner_id=owner_id,
                title=title,
                content=content,
                person_id=person_id,
                occurred_at=datetime.fromisoformat(occurred_at.replace("Z", "+00:00")) if occurred_at else None,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            enqueue_memory_embedding(row.id, owner_id)
            return MemoryOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="note_search")
    def note_search_mcp(query: str = "", person_id: str | None = None) -> list[dict]:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            statement = select(Memory).where(Memory.owner_id == owner_id)
            if query:
                statement = statement.where(Memory.title.ilike(f"%{query}%") | Memory.content.ilike(f"%{query}%"))
            if person_id:
                owned_person(db, person_id, db.get(User, owner_id))
                statement = statement.where(Memory.person_id == person_id)
            rows = db.scalars(statement.order_by(Memory.created_at.desc()).limit(100)).all()
            return [MemoryOut.model_validate(row).model_dump(mode="json") for row in rows]

    @mcp.tool(name="note_get")
    def note_get_mcp(note_id: str) -> dict:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Memory).where(Memory.id == note_id, Memory.owner_id == owner_id))
            if row is None:
                raise ValueError("Notiz nicht gefunden")
            return MemoryOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="note_update")
    def note_update_mcp(note_id: str, title: str | None = None, content: str | None = None, person_id: str | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Memory).where(Memory.id == note_id, Memory.owner_id == owner_id))
            if row is None:
                raise ValueError("Notiz nicht gefunden")
            if person_id is not None:
                owned_person(db, person_id, db.get(User, owner_id))
                row.person_id = person_id
            if title is not None:
                row.title = title
            if content is not None:
                row.content = content
            db.commit()
            db.refresh(row)
            enqueue_memory_embedding(row.id, owner_id)
            return MemoryOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="note_delete")
    def note_delete_mcp(note_id: str) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Memory).where(Memory.id == note_id, Memory.owner_id == owner_id))
            if row is None:
                raise ValueError("Notiz nicht gefunden")
            from lifepilot.mcp_tools import request_approval

            return request_approval(db, owner_id, "memory_delete", row.id, row.title)

    @mcp.tool(name="memory_review")
    def memory_review_mcp(capture_id: str, accepted_indices: list[int], person_assignments: dict[int, str] | None = None, related_person_assignments: dict[int, str] | None = None, project_assignments: dict[int, str] | None = None, create_people: list[int] | None = None, create_related_people: list[int] | None = None, confirmations: list[int] | None = None, suggestions: list[CaptureSuggestion] | None = None) -> list[dict]:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            if db.scalar(select(Capture.id).where(Capture.id == capture_id, Capture.owner_id == owner_id)) is None:
                raise ValueError("Eingabe nicht gefunden")
            created = capture_review(capture_id, CaptureReviewIn(accepted_indices=accepted_indices, person_assignments=person_assignments or {}, related_person_assignments=related_person_assignments or {}, project_assignments=project_assignments or {}, create_people=create_people or [], create_related_people=create_related_people or [], confirmations=confirmations or [], suggestions=suggestions), db, db.get(User, owner_id))
            return [row.model_dump(mode="json") for row in created]

    @mcp.tool(name="relationship_update")
    def relationship_update_mcp(
        relationship_id: str,
        relationship_type: str | None = None,
        inverse_relationship_type: str | None = None,
        valid_from: str | None = None,
        valid_until: str | None = None,
        confirmed: bool | None = None,
    ) -> dict:
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            row = db.scalar(select(Relationship).where(Relationship.id == relationship_id, Relationship.owner_id == owner_id))
            if row is None:
                raise ValueError("Beziehung nicht gefunden")
            if relationship_type is not None:
                row.relationship_type = relationship_type
            if inverse_relationship_type is not None:
                row.inverse_relationship_type = inverse_relationship_type
            if valid_from is not None:
                row.valid_from = datetime.fromisoformat(valid_from.replace("Z", "+00:00"))
            if valid_until is not None:
                row.valid_until = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
            if confirmed is not None:
                row.confirmed = confirmed
            if row.valid_from and row.valid_until and row.valid_until < row.valid_from:
                raise ValueError("Das Ende der Gültigkeit muss nach dem Beginn liegen")
            db.commit()
            db.refresh(row)
            from lifepilot.entity_embedding_jobs import enqueue_entity_embedding

            enqueue_entity_embedding("relationship", row.id, owner_id)
            from lifepilot.main import relationship_list

            return next(item.model_dump(mode="json") for item in relationship_list(db, db.get(User, owner_id), row.source_person_id) if item.id == row.id)

    @mcp.tool(name="event_search")
    def event_search_mcp(from_at: str | None = None, to_at: str | None = None, person_id: str | None = None) -> list[dict]:
        from lifepilot.planner import event_list

        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            start = datetime.fromisoformat(from_at.replace("Z", "+00:00")) if from_at else None
            end = datetime.fromisoformat(to_at.replace("Z", "+00:00")) if to_at else None
            return [row.model_dump(mode="json") for row in event_list(db, db.get(User, owner_id), start, end, person_id)]

    @mcp.tool(name="reminder_search")
    def reminder_search_mcp(state: str | None = None) -> list[dict]:
        owner_id = mcp_user()
        with mcp_session(owner_id) as db:
            statement = select(Reminder).where(Reminder.owner_id == owner_id)
            if state is not None:
                statement = statement.where(Reminder.state == state)
            return [ReminderOut.model_validate(row).model_dump(mode="json") for row in db.scalars(statement.order_by(Reminder.due_at)).all()]

    @mcp.tool(name="conversation_delete")
    def conversation_delete_mcp(conversation_id: str) -> dict:
        return _request_delete(mcp_user("memory:write"), Conversation, conversation_id, "conversation_delete")

    @mcp.tool(name="task_delete")
    def task_delete_mcp(task_id: str) -> dict:
        return _request_delete(mcp_user("memory:write"), Task, task_id, "task_delete")

    @mcp.tool(name="event_delete")
    def event_delete_mcp(event_id: str) -> dict:
        return _request_delete(mcp_user("memory:write"), Event, event_id, "event_delete")

    @mcp.tool(name="reminder_delete")
    def reminder_delete_mcp(reminder_id: str) -> dict:
        return _request_delete(mcp_user("memory:write"), Reminder, reminder_id, "reminder_delete")

    @mcp.tool(name="loan_delete")
    def loan_delete_mcp(loan_id: str) -> dict:
        return _request_delete(mcp_user("memory:write"), Loan, loan_id, "loan_delete")

    @mcp.tool(name="gift_delete")
    def gift_delete_mcp(gift_id: str) -> dict:
        return _request_delete(mcp_user("memory:write"), Gift, gift_id, "gift_delete")

    @mcp.tool(name="person_merge")
    def person_merge_mcp(source_person_id: str, target_person_id: str, confirm: bool = False) -> dict:
        if not confirm:
            raise ValueError("Personenzusammenführung ist dauerhaft. Setze confirm=true, um fortzufahren.")
        owner_id = mcp_user("memory:write")
        with mcp_session(owner_id) as db:
            source = owned_person(db, source_person_id, db.get(User, owner_id))
            target = owned_person(db, target_person_id, db.get(User, owner_id))
            if source.id == target.id:
                raise ValueError("Quell- und Zielperson müssen verschieden sein")

            for field in ("nickname", "birthday", "email", "phone", "address", "website", "job_title", "organization"):
                if not getattr(target, field):
                    setattr(target, field, getattr(source, field))
            if source.notes:
                target.notes = "\n\n".join(value for value in (target.notes, source.notes) if value)

            for row in db.scalars(select(Memory).where(Memory.owner_id == owner_id, Memory.person_id == source.id)):
                row.person_id = target.id
            for row in db.scalars(select(Task).where(Task.owner_id == owner_id, Task.person_id == source.id)):
                row.person_id = target.id
            for row in db.scalars(select(Loan).where(Loan.owner_id == owner_id)):
                if row.lender_person_id == source.id:
                    row.lender_person_id = target.id
                if row.borrower_person_id == source.id:
                    row.borrower_person_id = target.id
            for row in db.scalars(select(Gift).where(Gift.owner_id == owner_id, Gift.person_id == source.id)):
                row.person_id = target.id

            for link_model in (ConversationParticipant, EventParticipant):
                source_links = db.scalars(select(link_model).where(link_model.owner_id == owner_id, link_model.person_id == source.id)).all()
                for link in source_links:
                    parent_id = link.conversation_id if link_model is ConversationParticipant else link.event_id
                    existing = db.get(link_model, (parent_id, target.id))
                    if existing:
                        db.delete(link)
                    else:
                        link.person_id = target.id

            relationships = db.scalars(
                select(Relationship).where(
                    Relationship.owner_id == owner_id,
                    (Relationship.source_person_id == source.id) | (Relationship.target_person_id == source.id),
                )
            ).all()
            for relation in relationships:
                if relation.source_person_id == source.id:
                    relation.source_person_id = target.id
                if relation.target_person_id == source.id:
                    relation.target_person_id = target.id
                if relation.source_person_id == relation.target_person_id:
                    delete_entity_embedding(db, "relationship", relation.id, owner_id)
                    db.delete(relation)

            owner_relations = db.scalars(select(UserPersonRelationship).where(UserPersonRelationship.owner_id == owner_id, UserPersonRelationship.person_id == source.id)).all()
            for relation in owner_relations:
                duplicate = db.scalar(select(UserPersonRelationship.id).where(UserPersonRelationship.owner_id == owner_id, UserPersonRelationship.person_id == target.id, UserPersonRelationship.relationship_type == relation.relationship_type, UserPersonRelationship.valid_until.is_(None)))
                if duplicate is not None:
                    db.delete(relation)
                else:
                    relation.person_id = target.id

            db.add(AuditEvent(owner_id=owner_id, action="merge", resource_type="people", resource_id=source.id, source="mcp"))
            source_name = f"{source.first_name} {source.last_name}".strip()
            db.delete(source)
            db.commit()
            enqueue_person_context_embeddings(db, target.id, owner_id)
            return {"merged_person_id": source_person_id, "target_person_id": target.id, "merged_name": source_name}

