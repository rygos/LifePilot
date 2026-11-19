import json
from datetime import datetime, timezone
from typing import assert_never
from zoneinfo import ZoneInfo

from redis import Redis
from rq import Queue
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from lifepilot.capture_ai import ProviderError, extract_facts
from lifepilot.capture_schemas import CaptureSuggestion
from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import Capture, Conversation, ConversationParticipant, Event, Loan, Memory, Person, PersonLifeEvent, PersonNameHistory, Project, Relationship, Task, User, UserPersonRelationship
from lifepilot.services import owner_relationship_types

CAPTURE_QUEUE_NAME = "lifepilot"


def enqueue_capture_job(capture_id: str, owner_id: str) -> None:
    redis_client = Redis.from_url(settings.redis_url)
    try:
        queue = Queue(CAPTURE_QUEUE_NAME, connection=redis_client)
        queue.enqueue(
            "lifepilot.capture_jobs.process_capture_job",
            capture_id,
            owner_id,
            job_timeout=settings.llm_timeout_seconds + 15,
            result_ttl=3600,
            failure_ttl=86400,
            description="Schnellerfassung analysieren",
        )
    finally:
        redis_client.close()


def process_capture_job(capture_id: str, owner_id: str) -> str:
    with Session(engine) as db:
        capture = db.scalar(select(Capture).where(Capture.id == capture_id, Capture.owner_id == owner_id))
        if capture is None:
            return "missing"
        owner = db.get(User, owner_id)
        captured_at = capture.created_at or datetime.now(timezone.utc)
        captured_at = capture_time_in_timezone(captured_at, owner.timezone_name if owner else "UTC")
        try:
            lineage = _capture_thread_ancestors(capture, db)
            prior_context = _format_capture_thread_context(lineage)
            suggestions = extract_facts(capture.original_text, captured_at, prior_context) if prior_context else extract_facts(capture.original_text, captured_at)
        except ProviderError as error:
            if db.scalar(select(Capture.id).where(Capture.id == capture_id, Capture.owner_id == owner_id)) is None:
                return "missing"
            capture.status = "failed"
            capture.processing_error = str(error)
        else:
            if db.scalar(select(Capture.id).where(Capture.id == capture_id, Capture.owner_id == owner_id)) is None:
                return "missing"
            if suggestions is None:
                capture.status = "unavailable"
                capture.processing_error = "KI ist nicht konfiguriert. Der Originaltext wurde gespeichert."
            else:
                prior_suggestions = [
                    CaptureSuggestion.model_validate(item)
                    for ancestor in lineage
                    for item in json.loads(ancestor.suggestions_json)
                ]
                _save_suggestions(capture, suggestions, db, prior_suggestions)
        db.commit()
        return capture.status


def capture_time_in_timezone(captured_at: datetime, timezone_name: str) -> datetime:
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    return captured_at.astimezone(ZoneInfo(timezone_name))


def _capture_thread_context(capture: Capture, db: Session) -> str:
    return _format_capture_thread_context(_capture_thread_ancestors(capture, db))


def _capture_thread_ancestors(capture: Capture, db: Session) -> list[Capture]:
    if capture.parent_capture_id is None:
        return []
    lineage: list[Capture] = []
    parent_id: str | None = capture.parent_capture_id
    while parent_id and len(lineage) < 8:
        parent = db.scalar(select(Capture).where(Capture.id == parent_id, Capture.owner_id == capture.owner_id))
        if parent is None:
            break
        lineage.append(parent)
        parent_id = parent.parent_capture_id
    return list(reversed(lineage))


def _format_capture_thread_context(lineage: list[Capture]) -> str:
    sections: list[str] = []
    for parent in lineage:
        suggestions = json.loads(parent.suggestions_json)
        summary = "\n".join(
            f"- {item.get('kind')}: {item.get('title')} — {item.get('content')}"
            for item in suggestions
        )
        sections.append(f"Bisherige Nutzereingabe: {parent.original_text}\nDamals vorgeschlagene Struktur:\n{summary or '- Keine Vorschläge'}")
    return "\n\n".join(sections)[-12000:]


def _save_suggestions(
    capture: Capture,
    suggestions: list[CaptureSuggestion],
    db: Session,
    prior_suggestions: list[CaptureSuggestion] | None = None,
) -> None:
    people = db.scalars(select(Person).where(Person.owner_id == capture.owner_id)).all()
    projects = db.scalars(select(Project).where(Project.owner_id == capture.owner_id)).all()
    aliases = db.scalars(select(PersonNameHistory).where(PersonNameHistory.owner_id == capture.owner_id, PersonNameHistory.confirmed.is_(True))).all()
    aliases_by_person: dict[str, set[str]] = {}
    for alias in aliases:
        aliases_by_person.setdefault(alias.person_id, set()).add(alias.name.casefold())
    resolved: list[CaptureSuggestion] = []
    omitted_duplicates = 0
    for suggestion in suggestions:
        person_matches = []
        if suggestion.person_name:
            needle = suggestion.person_name.strip().casefold()
            person_matches = [person for person in people if needle in {person.first_name.casefold(), f"{person.first_name} {person.last_name}".strip().casefold(), (person.nickname or "").casefold()} | aliases_by_person.get(person.id, set())]
        project_needle = (suggestion.project_name or "").strip().casefold()
        project_matches = [
            project
            for project in projects
            if project_needle
            and (
                project_needle == project.name.strip().casefold()
                or project_needle in project.name.strip().casefold()
                or project_needle in project.description.strip().casefold()
            )
        ]
        related_matches = [person for person in people if suggestion.related_person_name and suggestion.related_person_name.strip().casefold() in {person.first_name.casefold(), f"{person.first_name} {person.last_name}".strip().casefold(), (person.nickname or "").casefold()} | aliases_by_person.get(person.id, set())]
        item = suggestion.model_copy(update={
            "person_id": person_matches[0].id if len(person_matches) == 1 else None,
            "person_candidates": [person.id for person in person_matches[:5]],
            "project_id": project_matches[0].id if len(project_matches) == 1 else None,
            "project_candidates": [project.id for project in project_matches[:5]],
            "related_person_id": related_matches[0].id if len(related_matches) == 1 else None,
            "related_person_candidates": [person.id for person in related_matches[:5]],
            "confirmation_required": suggestion.confirmation_required or len(person_matches) > 1 or len(project_matches) > 1 or len(related_matches) > 1,
        })
        if _already_saved(item, db, capture.owner_id):
            omitted_duplicates += 1
            continue
        resolved.append(item)
    seen_suggestions = {_suggestion_key(item) for item in prior_suggestions or []}
    distinct: list[CaptureSuggestion] = []
    for suggestion in resolved:
        key = _suggestion_key(suggestion)
        if key in seen_suggestions:
            omitted_duplicates += 1
            continue
        seen_suggestions.add(key)
        distinct.append(suggestion)
    capture.status = "ready"
    capture.processing_error = f"{omitted_duplicates} bereits gespeicherte oder doppelte Vorschläge ausgeblendet." if omitted_duplicates else ""
    capture.suggestions_json = json.dumps(
        [item.model_dump(mode="json") for item in distinct], ensure_ascii=False
    )


def _suggestion_key(suggestion: CaptureSuggestion) -> tuple[str, str, str, str]:
    person = (suggestion.person_id or suggestion.person_name or "").strip().casefold()
    related = (suggestion.related_person_id or suggestion.related_person_name or "").strip().casefold()
    match suggestion.kind:
        case "relationship":
            return suggestion.kind, person, (suggestion.relationship_type or "").casefold(), related
        case "owner_relationship":
            return suggestion.kind, person, (suggestion.relationship_type or "").casefold(), ""
        case "former_name":
            return suggestion.kind, person, (suggestion.former_name or "").casefold(), ""
        case "conversation" | "event":
            date = suggestion.occurred_at.date().isoformat() if suggestion.occurred_at else ""
            return suggestion.kind, person, " ".join(suggestion.title.casefold().split()), date
        case "loan":
            return suggestion.kind, person, suggestion.loan_direction or "borrowed", " ".join(suggestion.title.casefold().split())
        case "life_event":
            return suggestion.kind, person, " ".join(suggestion.title.casefold().split()), ""
        case _:
            return (
                suggestion.kind,
                person,
                " ".join(suggestion.title.casefold().split()),
                " ".join(suggestion.content.casefold().split()),
            )


def _already_saved(suggestion: CaptureSuggestion, db: Session, owner_id: str) -> bool:
    person_id = suggestion.person_id
    related_id = suggestion.related_person_id
    normalized_title = " ".join(suggestion.title.casefold().split())
    match suggestion.kind:
        case "relationship":
            if person_id is None or related_id is None:
                return False
            rows = db.scalars(select(Relationship).where(Relationship.owner_id == owner_id, or_(
                (Relationship.source_person_id == person_id) & (Relationship.target_person_id == related_id),
                (Relationship.source_person_id == related_id) & (Relationship.target_person_id == person_id),
            ))).all()
            requested = (suggestion.relationship_type or "").casefold()
            inverse = (suggestion.inverse_relationship_type or "").casefold()
            return any(row.relationship_type.casefold() in {requested, inverse} or row.inverse_relationship_type.casefold() in {requested, inverse} for row in rows)
        case "owner_relationship":
            if person_id is None:
                return False
            legacy_link = db.scalar(select(UserPersonRelationship.id).where(UserPersonRelationship.owner_id == owner_id, UserPersonRelationship.person_id == person_id, UserPersonRelationship.relationship_type == suggestion.relationship_type, UserPersonRelationship.valid_until.is_(None)))
            self_id = db.scalar(select(Person.id).where(Person.owner_id == owner_id, Person.is_self.is_(True)))
            if self_id is None:
                return bool(legacy_link)
            relation_type, inverse_type = owner_relationship_types(suggestion.relationship_type or "")
            graph_rows = db.scalars(select(Relationship).where(Relationship.owner_id == owner_id, or_(
                (Relationship.source_person_id == person_id) & (Relationship.target_person_id == self_id),
                (Relationship.source_person_id == self_id) & (Relationship.target_person_id == person_id),
            ))).all()
            graph_link = any(
                row.relationship_type in {relation_type, inverse_type}
                or row.inverse_relationship_type in {relation_type, inverse_type}
                for row in graph_rows
            )
            return bool(legacy_link or graph_link)
        case "former_name":
            alias = (suggestion.former_name or "").casefold()
            return bool(person_id and alias and db.scalar(select(PersonNameHistory.id).where(PersonNameHistory.owner_id == owner_id, PersonNameHistory.person_id == person_id, PersonNameHistory.name_type == "former", func.lower(PersonNameHistory.name) == alias, PersonNameHistory.confirmed.is_(True))))
        case "life_event":
            return bool(person_id and db.scalar(select(PersonLifeEvent.id).where(PersonLifeEvent.owner_id == owner_id, PersonLifeEvent.person_id == person_id, func.lower(PersonLifeEvent.title) == normalized_title)))
        case "conversation":
            if person_id is None or suggestion.occurred_at is None:
                return False
            start = suggestion.occurred_at.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
            return bool(db.scalar(select(Conversation.id).join(ConversationParticipant, ConversationParticipant.conversation_id == Conversation.id).where(Conversation.owner_id == owner_id, ConversationParticipant.person_id == person_id, Conversation.occurred_at >= start, Conversation.occurred_at <= end, func.lower(Conversation.title) == normalized_title)))
        case "loan":
            person_column = Loan.borrower_person_id if suggestion.loan_direction == "lent" else Loan.lender_person_id
            return bool(person_id and db.scalar(select(Loan.id).where(Loan.owner_id == owner_id, person_column == person_id, func.lower(Loan.item_name) == normalized_title, Loan.returned_at.is_(None))))
        case "task":
            return bool(db.scalar(select(Task.id).where(Task.owner_id == owner_id, func.lower(Task.title) == normalized_title, Task.status == "open", Task.person_id == person_id)))
        case "event":
            return bool(suggestion.occurred_at and db.scalar(select(Event.id).where(Event.owner_id == owner_id, func.lower(Event.title) == normalized_title, Event.starts_at == suggestion.occurred_at)))
        case "fact" | "project_link":
            normalized_content = " ".join(suggestion.content.casefold().split())
            memories = db.scalars(select(Memory).where(Memory.owner_id == owner_id, Memory.person_id == person_id)).all()
            return any(" ".join(row.content.casefold().split()) == normalized_content for row in memories)
        case unreachable:
            assert_never(unreachable)
