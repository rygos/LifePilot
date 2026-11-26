import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import TypeAdapter
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from redis.exceptions import RedisError

from lifepilot.capture_jobs import enqueue_capture_job
from lifepilot.capture_schemas import AcceptedMemory, CaptureIn, CaptureOut, CaptureReviewIn, CaptureSuggestion
from lifepilot.config import settings
from lifepilot.db import get_db
from lifepilot.embedding_jobs import enqueue_memory_embedding
from lifepilot.entity_embedding_jobs import enqueue_entity_embedding
from lifepilot.models import Capture, Conversation, ConversationParticipant, ConversationProject, Event, EventParticipant, Gift, Loan, Memory, MemoryProject, Person, PersonLifeEvent, PersonNameHistory, Project, Relationship, Reminder, Task, User
from lifepilot.security import current_user
from lifepilot.models import Commitment, AuditEvent
from lifepilot.revisions import record_conversation_revision, record_task_revision
from lifepilot.services import ensure_self_person, owner_relationship_types, relationship_create

router = APIRouter(prefix="/api/captures", tags=["Eingang"])
suggestion_list = TypeAdapter(list[CaptureSuggestion])


def capture_output(row: Capture) -> CaptureOut:
    return CaptureOut(
        id=row.id,
        parent_capture_id=row.parent_capture_id,
        original_text=row.original_text,
        source=row.source,
        status=row.status,
        suggestions=suggestion_list.validate_json(row.suggestions_json),
        processing_error=row.processing_error,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


def _resolve_person(db: Session, owner: User, suggestion: CaptureSuggestion, assignment: str | None) -> Person | None:
    person_id = assignment or suggestion.person_id
    if person_id:
        person = db.scalar(select(Person).where(Person.id == person_id, Person.owner_id == owner.id))
        if person is None:
            raise HTTPException(status_code=404, detail="Zugeordnete Person nicht gefunden")
        return person
    if not suggestion.person_name:
        return None
    term = suggestion.person_name.strip()
    rows = db.scalars(select(Person).where(Person.owner_id == owner.id, or_(Person.first_name.ilike(term), (Person.first_name + " " + Person.last_name).ilike(term), Person.nickname.ilike(term))).limit(6)).all()
    return rows[0] if len(rows) == 1 else None


def _resolve_project(db: Session, owner: User, suggestion: CaptureSuggestion, assignment: str | None) -> Project | None:
    project_id = assignment or suggestion.project_id
    if project_id:
        project = db.scalar(select(Project).where(Project.id == project_id, Project.owner_id == owner.id))
        if project is None:
            raise HTTPException(status_code=404, detail="Zugeordnetes Projekt nicht gefunden")
        return project
    if not suggestion.project_name:
        return None
    term = suggestion.project_name.strip()
    rows = db.scalars(select(Project).where(Project.owner_id == owner.id, Project.name.ilike(term)).limit(6)).all()
    return rows[0] if len(rows) == 1 else None


def _create_person_from_explicit_name(db: Session, owner: User, name: str, created: dict[str, Person]) -> Person:
    normalized = " ".join(name.split())
    if not normalized:
        raise HTTPException(status_code=422, detail="Zum Anlegen einer Person wird ein Name benötigt")
    key = normalized.casefold()
    if key not in created:
        first_name, _, last_name = normalized.partition(" ")
        person = Person(owner_id=owner.id, first_name=first_name, last_name=last_name)
        db.add(person)
        db.flush()
        created[key] = person
    return created[key]


@router.post("", response_model=CaptureOut, status_code=201)
def capture_create(data: CaptureIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> CaptureOut:
    parent = db.scalar(select(Capture).where(Capture.id == data.parent_capture_id, Capture.owner_id == user.id)) if data.parent_capture_id else None
    if data.parent_capture_id and parent is None:
        raise HTTPException(status_code=404, detail="Die zugehörige Erfassung wurde nicht gefunden")
    row = Capture(owner_id=user.id, parent_capture_id=parent.id if parent else None, original_text=data.original_text.strip(), source=data.source)
    if not row.original_text:
        raise HTTPException(status_code=422, detail="Die Eingabe darf nicht leer sein")
    db.add(row)
    db.commit()
    db.refresh(row)
    if settings.llm_base_url and settings.llm_model and settings.redis_url:
        try:
            enqueue_capture_job(row.id, user.id)
        except RedisError:
            row.status = "failed"
            row.processing_error = "Die Verarbeitungswarteschlange ist nicht erreichbar. Der Originaltext bleibt gespeichert."
    elif not settings.llm_base_url or not settings.llm_model:
        row.status = "unavailable"
        row.processing_error = "KI ist nicht konfiguriert. Der Originaltext wurde gespeichert."
    else:
        row.status = "failed"
        row.processing_error = "Redis ist für die KI-Warteschlange nicht konfiguriert. Der Originaltext bleibt gespeichert."
    db.commit()
    db.refresh(row)
    return capture_output(row)


@router.get("", response_model=list[CaptureOut])
def capture_list(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[CaptureOut]:
    rows = db.scalars(select(Capture).where(Capture.owner_id == user.id).order_by(Capture.created_at.desc()).limit(100)).all()
    return [capture_output(row) for row in rows]


@router.post("/{capture_id}/review", response_model=list[AcceptedMemory], status_code=201)
def capture_review(capture_id: str, data: CaptureReviewIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[AcceptedMemory]:
    row = db.scalar(select(Capture).where(Capture.id == capture_id, Capture.owner_id == user.id).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(status_code=404, detail="Eingabe nicht gefunden")
    if row.status != "ready":
        raise HTTPException(status_code=409, detail="Diese Eingabe enthält keine prüfbaren Vorschläge")
    suggestions = data.suggestions or suggestion_list.validate_json(row.suggestions_json)
    accepted_indices = data.accepted_indices
    if len(set(accepted_indices)) != len(accepted_indices) or any(index < 0 or index >= len(suggestions) for index in accepted_indices):
        raise HTTPException(status_code=422, detail="Mindestens eine Vorschlagsauswahl ist ungültig")
    if any(index not in accepted_indices for index in [*data.person_assignments, *data.related_person_assignments, *data.project_assignments, *data.create_people, *data.create_related_people, *data.confirmations]):
        raise HTTPException(status_code=422, detail="Zuordnungen und Bestätigungen müssen ausgewählte Vorschläge betreffen")
    if len(set(data.create_people)) != len(data.create_people) or len(set(data.create_related_people)) != len(data.create_related_people):
        raise HTTPException(status_code=422, detail="Personen können pro Vorschlag nur einmal neu angelegt werden")
    if set(data.create_people) & set(data.person_assignments) or set(data.create_related_people) & set(data.related_person_assignments):
        raise HTTPException(status_code=422, detail="Bitte eine vorhandene Person zuordnen oder eine neue Person anlegen")
    create_indices = set(data.create_people) | set(data.create_related_people)
    if any(index not in data.confirmations for index in create_indices):
        raise HTTPException(status_code=422, detail="Neue Personen müssen ausdrücklich bestätigt werden")
    if any(suggestions[index].confirmation_required and index not in data.confirmations for index in accepted_indices):
        raise HTTPException(status_code=422, detail="Mindestens ein Vorschlag benötigt eine ausdrückliche Bestätigung")
    if any(
        (
            suggestions[index].person_gender_basis == "name_inference"
            or suggestions[index].related_person_gender_basis == "name_inference"
        )
        and index not in data.confirmations
        for index in accepted_indices
    ):
        raise HTTPException(status_code=422, detail="Geschlechtsvermutungen müssen ausdrücklich bestätigt werden")
    accepted: list[AcceptedMemory] = []
    memory_rows: list[Memory] = []
    created_people: dict[str, Person] = {}
    try:
        for index in accepted_indices:
            suggestion = suggestions[index]
            person = _create_person_from_explicit_name(db, user, suggestion.person_name, created_people) if index in data.create_people and suggestion.person_name else _resolve_person(db, user, suggestion, data.person_assignments.get(index))
            project = _resolve_project(db, user, suggestion, data.project_assignments.get(index))
            if suggestion.person_name and person is None:
                raise HTTPException(status_code=422, detail=f"Person für Vorschlag {index + 1} ist nicht eindeutig zugeordnet")
            if person and person.gender == "unspecified" and suggestion.person_gender:
                person.gender = suggestion.person_gender
            if suggestion.kind in {"former_name", "life_event"} and index not in data.confirmations:
                raise HTTPException(status_code=422, detail="Biografische Angaben müssen ausdrücklich bestätigt werden")
            match suggestion.kind:
                case "commitment":
                    if index not in data.confirmations:
                        raise HTTPException(422, "Verpflichtungen müssen ausdrücklich bestätigt werden")
                    evidence = (suggestion.commitment_evidence or "").strip()
                    if not evidence or evidence not in row.original_text or not suggestion.commitment_direction or person is None:
                        raise HTTPException(422, "Verpflichtung benötigt eine belegte Zusage, Richtung und Person")
                    if suggestion.project_name and project is None:
                        raise HTTPException(422, "Projekt muss zuerst eindeutig zugeordnet werden")
                    if suggestion.due_at and suggestion.due_at.tzinfo is None:
                        raise HTTPException(422, "Fälligkeit benötigt eine Zeitzone")
                    due_at = suggestion.due_at.astimezone(timezone.utc) if suggestion.due_at else None
                    commitment = Commitment(owner_id=user.id, title=suggestion.title, notes=suggestion.content, direction=suggestion.commitment_direction, person_id=person.id, project_id=project.id if project else None, due_at=due_at, source_capture_id=row.id, source_quote=evidence)
                    db.add(commitment)
                    db.flush()
                    db.add(AuditEvent(owner_id=user.id, action="create", resource_type="commitments", resource_id=commitment.id, source="capture"))
                    accepted.append(AcceptedMemory(id=commitment.id, title=commitment.title, kind="commitment", resource_id=commitment.id, resource_type="commitment"))
                case "conversation":
                    conversation = Conversation(owner_id=user.id, title=suggestion.title, original_note=row.original_text, summary=suggestion.content, location=suggestion.location or "", occurred_at=suggestion.occurred_at)
                    db.add(conversation)
                    db.flush()
                    attendees: dict[str, Person] = {}
                    if person:
                        attendees[person.id] = person
                    for attendee_name in suggestion.participant_names:
                        normalized_name = " ".join(attendee_name.split())
                        first_name = normalized_name.split(" ", 1)[0]
                        matches = db.scalars(select(Person).where(Person.owner_id == user.id, or_((Person.first_name + " " + Person.last_name).ilike(normalized_name), Person.first_name.ilike(normalized_name), Person.first_name.ilike(first_name))).limit(2)).all()
                        attendee = matches[0] if len(matches) == 1 else None
                        if attendee is None and not matches:
                            attendee = _create_person_from_explicit_name(db, user, normalized_name, created_people)
                        if attendee:
                            attendees[attendee.id] = attendee
                    for attendee in attendees.values():
                        db.add(ConversationParticipant(conversation_id=conversation.id, person_id=attendee.id, owner_id=user.id))
                    if project:
                        db.add(ConversationProject(conversation_id=conversation.id, project_id=project.id, owner_id=user.id))
                    record_conversation_revision(db, conversation, "created", "capture")
                    accepted.append(AcceptedMemory(id=conversation.id, title=conversation.title, kind=suggestion.kind, resource_id=conversation.id, resource_type="conversation"))
                    if suggestion.occurred_at is not None:
                        event_memory = Memory(owner_id=user.id, title=conversation.title, content=row.original_text, person_id=person.id if person else None, source="capture", source_capture_id=row.id, occurred_at=suggestion.occurred_at)
                        db.add(event_memory)
                        db.flush()
                        event = Event(owner_id=user.id, record_type="experience", title=suggestion.title, description=suggestion.content or row.original_text, location=suggestion.location or "", location_address=suggestion.location_address or "", starts_at=suggestion.occurred_at, source_memory_id=event_memory.id)
                        db.add(event)
                        db.flush()
                        for attendee in attendees.values():
                            db.add(EventParticipant(event_id=event.id, person_id=attendee.id, owner_id=user.id))
                        accepted.append(AcceptedMemory(id=event.id, title=event.title, kind="event", resource_id=event.id, resource_type="event"))
                case "former_name":
                    if person is None:
                        raise HTTPException(status_code=422, detail="Früherer Name benötigt eine Personenzuordnung")
                    name = suggestion.former_name or suggestion.content
                    history = PersonNameHistory(owner_id=user.id, person_id=person.id, name=name, name_type="former", valid_until=suggestion.occurred_at, source_capture_id=row.id, confirmed=True)
                    db.add(history)
                    db.flush()
                    accepted.append(AcceptedMemory(id=history.id, title=suggestion.title, kind=suggestion.kind, resource_id=history.id, resource_type="person_name"))
                case "life_event":
                    if person is None:
                        raise HTTPException(status_code=422, detail="Lebensereignis benötigt eine eindeutig zugeordnete Person")
                    life_event = PersonLifeEvent(owner_id=user.id, person_id=person.id, title=suggestion.title, details=suggestion.content, occurred_at=suggestion.occurred_at, date_precision=suggestion.date_precision, source_capture_id=row.id, confirmed=True)
                    db.add(life_event)
                    db.flush()
                    accepted.append(AcceptedMemory(id=life_event.id, title=life_event.title, kind=suggestion.kind, resource_id=life_event.id, resource_type="life_event"))
                case "relationship":
                    if person is None or not suggestion.related_person_name:
                        raise HTTPException(status_code=422, detail="Beziehung benötigt zwei eindeutig zugeordnete Personen")
                    related_id = data.related_person_assignments.get(index) or suggestion.related_person_id
                    related = _create_person_from_explicit_name(db, user, suggestion.related_person_name, created_people) if index in data.create_related_people and suggestion.related_person_name else db.scalar(select(Person).where(Person.id == related_id, Person.owner_id == user.id)) if related_id else None
                    if related is None:
                        matches = db.scalars(select(Person).where(Person.owner_id == user.id, or_(Person.first_name.ilike(suggestion.related_person_name), (Person.first_name + " " + Person.last_name).ilike(suggestion.related_person_name))).limit(2)).all()
                        related = matches[0] if len(matches) == 1 else None
                    if related is None:
                        raise HTTPException(status_code=422, detail="Zweite Person der Beziehung ist nicht eindeutig zugeordnet")
                    if related.gender == "unspecified" and suggestion.related_person_gender:
                        related.gender = suggestion.related_person_gender
                    memory = Memory(owner_id=user.id, title=suggestion.title, content=row.original_text, person_id=person.id, source="capture", source_capture_id=row.id, occurred_at=suggestion.occurred_at)
                    db.add(memory)
                    db.flush()
                    relationship = relationship_create(db, user, person.id, related.id, suggestion.relationship_type or "Beziehung zu", memory.id, True, suggestion.inverse_relationship_type, commit=False)
                    memory_rows.append(memory)
                    accepted.append(AcceptedMemory(id=relationship.id, title=suggestion.title, kind=suggestion.kind, resource_id=relationship.id, resource_type="relationship"))
                case "owner_relationship":
                    if person is None or not suggestion.relationship_type:
                        raise HTTPException(status_code=422, detail="Beziehung zum Nutzer benötigt eine Person und einen Beziehungstyp")
                    self_person = ensure_self_person(db, user)
                    relation_type, inverse_type = owner_relationship_types(suggestion.relationship_type)
                    memory = Memory(owner_id=user.id, title=suggestion.title, content=row.original_text, person_id=person.id, source="capture", source_capture_id=row.id, occurred_at=suggestion.occurred_at)
                    db.add(memory)
                    db.flush()
                    owner_edge = relationship_create(db, user, person.id, self_person.id, relation_type, memory.id, True, inverse_type, commit=False)
                    memory_rows.append(memory)
                    accepted.append(AcceptedMemory(id=owner_edge.id, title=suggestion.title, kind=suggestion.kind, resource_id=owner_edge.id, resource_type="relationship"))
                case "task":
                    task = Task(owner_id=user.id, title=suggestion.title, description=suggestion.content, person_id=person.id if person else None, project_id=project.id if project else None, due_at=suggestion.due_at)
                    db.add(task)
                    db.flush()
                    record_task_revision(db, task, "created", "capture")
                    if task.due_at:
                        db.add(Reminder(owner_id=user.id, title=task.title, due_at=task.due_at, task_id=task.id))
                    accepted.append(AcceptedMemory(id=task.id, title=task.title, kind=suggestion.kind, resource_id=task.id, resource_type="task"))
                case "event":
                    if suggestion.occurred_at is None:
                        raise HTTPException(status_code=422, detail="Termin benötigt einen konkreten Zeitpunkt")
                    event = Event(owner_id=user.id, title=suggestion.title, description=suggestion.content, location="", starts_at=suggestion.occurred_at, source_memory_id=None)
                    db.add(event)
                    db.flush()
                    if person:
                        db.add(EventParticipant(event_id=event.id, person_id=person.id, owner_id=user.id))
                    db.add(Reminder(owner_id=user.id, title=event.title, due_at=event.starts_at, event_id=event.id))
                    accepted.append(AcceptedMemory(id=event.id, title=event.title, kind=suggestion.kind, resource_id=event.id, resource_type="event"))
                case "loan":
                    if person is None:
                        raise HTTPException(status_code=422, detail="Leihgabe benötigt eine eindeutig zugeordnete Person als Verleiher")
                    memory = Memory(owner_id=user.id, title=f"Leihgabe: {suggestion.title}", content=row.original_text, person_id=person.id, source="capture", source_capture_id=row.id, occurred_at=suggestion.occurred_at)
                    db.add(memory)
                    db.flush()
                    borrowed = suggestion.loan_direction != "lent"
                    loan = Loan(owner_id=user.id, item_name=suggestion.title, lender_person_id=person.id if borrowed else None, borrower_person_id=person.id if not borrowed else None, lent_at=suggestion.occurred_at or row.created_at, due_at=suggestion.due_at, condition_note=suggestion.content, source_memory_id=memory.id)
                    db.add(loan)
                    db.flush()
                    memory_rows.append(memory)
                    accepted.append(AcceptedMemory(id=loan.id, title=loan.item_name, kind=suggestion.kind, resource_id=loan.id, resource_type="loan"))
                case "project_link":
                    if project is None:
                        raise HTTPException(status_code=422, detail="Projekt muss zuerst eindeutig zugeordnet werden")
                    memory = Memory(owner_id=user.id, title=suggestion.title, content=suggestion.content, person_id=person.id if person else None, source="capture", source_capture_id=row.id, occurred_at=suggestion.occurred_at)
                    db.add(memory)
                    db.flush()
                    db.add(MemoryProject(memory_id=memory.id, project_id=project.id, owner_id=user.id))
                    memory_rows.append(memory)
                    accepted.append(AcceptedMemory(id=memory.id, title=memory.title, kind=suggestion.kind, resource_id=memory.id, resource_type="memory"))
                case "fact":
                    memory = Memory(owner_id=user.id, title=suggestion.title, content=suggestion.content, person_id=person.id if person else None, source="capture", source_capture_id=row.id, occurred_at=suggestion.occurred_at)
                    db.add(memory)
                    db.flush()
                    if project:
                        db.add(MemoryProject(memory_id=memory.id, project_id=project.id, owner_id=user.id))
                    memory_rows.append(memory)
                    accepted.append(AcceptedMemory(id=memory.id, title=memory.title, kind=suggestion.kind, resource_id=memory.id, resource_type="memory"))
        remaining_suggestions = [item for index, item in enumerate(suggestions) if index not in accepted_indices]
        row.suggestions_json = json.dumps([item.model_dump(mode="json") for item in remaining_suggestions], ensure_ascii=False)
        row.status = "reviewed" if not remaining_suggestions else "ready"
        row.reviewed_at = datetime.now(timezone.utc) if not remaining_suggestions else None
        db.commit()
    except (HTTPException, ValueError):
        db.rollback()
        raise
    for memory in memory_rows:
        enqueue_memory_embedding(memory.id, user.id)
    for result in accepted:
        if result.resource_type in {"conversation", "task", "relationship"}:
            enqueue_entity_embedding(result.resource_type, result.id, user.id)
    return accepted


@router.delete("/{capture_id}", status_code=204)
def capture_delete(capture_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    row = db.scalar(select(Capture).where(Capture.id == capture_id, Capture.owner_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Eingabe nicht gefunden")
    db.delete(row)
    db.commit()
