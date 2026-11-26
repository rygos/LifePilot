from lifepilot.trash_routes import move_to_trash
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.attachment_routes import attachment_files_for_resource, remove_attachment_files
from lifepilot.entity_embedding_jobs import enqueue_entity_embedding
from lifepilot.models import AuditEvent, Event, EventParticipant, Memory, Person, Project, Reminder, Task, User
from lifepilot.recurrence import next_recurrence_at
from lifepilot.revisions import history, record_task_revision
from lifepilot.schemas import EventIn, EventOut, EventPatch, ReminderAction, ReminderIn, ReminderOut, TaskIn, TaskOut
from lifepilot.event_media import event_photo_files
from lifepilot.security import current_user
from lifepilot.services import is_quiet_hours, owned_person
from lifepilot.scheduler import sync_contact_followup

router = APIRouter()


def event_output(db: Session, event: Event, owner_id: str) -> EventOut:
    participant_ids = list(db.scalars(select(EventParticipant.person_id).where(EventParticipant.event_id == event.id, EventParticipant.owner_id == owner_id)).all())
    return EventOut(id=event.id, record_type=event.record_type, title=event.title, description=event.description, location=event.location, location_address=event.location_address, starts_at=event.starts_at, ends_at=event.ends_at, source_memory_id=event.source_memory_id, participant_ids=participant_ids)


def utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def stored_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.post("/api/tasks", response_model=TaskOut, status_code=201)
def task_create(data: TaskIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Task:
    owned_person(db, data.person_id, user)
    if data.project_id and db.scalar(select(Project.id).where(Project.id == data.project_id, Project.owner_id == user.id)) is None:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    task = Task(owner_id=user.id, **data.model_dump())
    db.add(task)
    db.flush()
    record_task_revision(db, task, "created", "rest")
    db.commit()
    db.refresh(task)
    enqueue_entity_embedding("task", task.id, user.id)
    return task


@router.get("/api/tasks", response_model=list[TaskOut])
def task_list(db: Session = Depends(get_db), user: User = Depends(current_user), status: str | None = None) -> list[Task]:
    stmt = select(Task).where(Task.owner_id == user.id)
    if status:
        stmt = stmt.where(Task.status == status)
    return list(db.scalars(stmt.order_by(Task.due_at.is_(None), Task.due_at)).all())


@router.patch("/api/tasks/{task_id}", response_model=TaskOut)
def task_update(task_id: str, data: TaskIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Task:
    return update_task(db, user, task_id, data, source="rest")


def update_task(db: Session, user: User, task_id: str, data: TaskIn, source: str = "rest") -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id, Task.owner_id == user.id).with_for_update())
    if task is None:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
    owned_person(db, data.person_id, user)
    if data.project_id and db.scalar(select(Project.id).where(Project.id == data.project_id, Project.owner_id == user.id)) is None:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    previous_due_at = utc_datetime(task.due_at) if task.due_at is not None else None
    for field, value in data.model_dump().items():
        setattr(task, field, value)
    record_task_revision(db, task, "updated", source)
    reminder = db.scalar(select(Reminder).where(Reminder.task_id == task.id, Reminder.owner_id == user.id))
    current_due_at = utc_datetime(task.due_at) if task.due_at is not None else None
    if reminder is not None:
        if current_due_at is None:
            db.delete(reminder)
        else:
            reminder.title = task.title
            if previous_due_at != current_due_at:
                reminder.due_at = current_due_at
                reminder.snoozed_until = None
                if task.status == "open" and reminder.state != "muted":
                    reminder.state = "scheduled"
    elif current_due_at is not None and task.status == "open":
        db.add(Reminder(owner_id=user.id, title=task.title, due_at=current_due_at, task_id=task.id))
    db.commit()
    db.refresh(task)
    enqueue_entity_embedding("task", task.id, user.id)
    return task


@router.delete("/api/tasks/{task_id}", status_code=204)
def task_delete(task_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    task = db.scalar(select(Task).where(Task.id == task_id, Task.owner_id == user.id))
    if task is None:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
    move_to_trash(db, user.id, Task, task.id)
    db.commit()


@router.patch("/api/tasks/{task_id}/complete", response_model=TaskOut)
def task_complete(task_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id, Task.owner_id == user.id).with_for_update())
    if task is None:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
    if task.status == "done":
        return task
    task.status = "done"
    record_task_revision(db, task, "updated", "rest")
    next_task: Task | None = None
    reminder = db.scalar(select(Reminder).where(Reminder.task_id == task.id, Reminder.owner_id == user.id, Reminder.state == "scheduled"))
    if reminder is not None:
        reminder.state = "done"
    if task.repeat_interval_days is not None and task.due_at is not None:
        next_due_at = next_recurrence_at(task.due_at, task.repeat_interval_days, task.repeat_until)
        if next_due_at is not None:
            next_task = Task(owner_id=task.owner_id, person_id=task.person_id, project_id=task.project_id, title=task.title, description=task.description, due_at=next_due_at, repeat_interval_days=task.repeat_interval_days, repeat_until=task.repeat_until, priority=task.priority, estimated_minutes=task.estimated_minutes, mental_effort=task.mental_effort, start_friction=task.start_friction, work_context=task.work_context, next_step=task.next_step)
            db.add(next_task)
            db.flush()
            record_task_revision(db, next_task, "created", "recurrence")
            db.add(Reminder(owner_id=task.owner_id, title=task.title, due_at=next_due_at, task_id=next_task.id))
    db.commit()
    db.refresh(task)
    enqueue_entity_embedding("task", task.id, user.id)
    if next_task is not None:
        enqueue_entity_embedding("task", next_task.id, user.id)
    return task


@router.get("/api/tasks/{task_id}/history")
def task_history(task_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return history(db, user.id, "task", task_id)


@router.post("/api/events", response_model=EventOut, status_code=201)
def event_create(data: EventIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> EventOut:
    participant_ids = list(dict.fromkeys(data.participant_ids))
    if participant_ids:
        valid_ids = set(db.scalars(select(Person.id).where(Person.owner_id == user.id, Person.id.in_(participant_ids))).all())
        if valid_ids != set(participant_ids):
            raise HTTPException(status_code=404, detail="Mindestens eine beteiligte Person wurde nicht gefunden")
    if data.source_memory_id and db.scalar(select(Memory.id).where(Memory.id == data.source_memory_id, Memory.owner_id == user.id)) is None:
        raise HTTPException(status_code=404, detail="Quellerinnerung nicht gefunden")
    if data.ends_at and utc_datetime(data.ends_at) < utc_datetime(data.starts_at):
        raise HTTPException(status_code=422, detail="Das Ende muss nach dem Beginn liegen")
    event_data = data.model_dump(exclude={"participant_ids"})
    event_data["starts_at"] = stored_utc(event_data["starts_at"])
    if event_data["ends_at"] is not None:
        event_data["ends_at"] = stored_utc(event_data["ends_at"])
    event = Event(owner_id=user.id, **event_data)
    db.add(event)
    db.flush()
    db.add_all(EventParticipant(event_id=event.id, person_id=person_id, owner_id=user.id) for person_id in participant_ids)
    db.commit()
    db.refresh(event)
    return EventOut(id=event.id, record_type=event.record_type, title=event.title, description=event.description, location=event.location, location_address=event.location_address, starts_at=event.starts_at, ends_at=event.ends_at, source_memory_id=event.source_memory_id, participant_ids=participant_ids)


@router.get("/api/events", response_model=list[EventOut])
def event_list(db: Session = Depends(get_db), user: User = Depends(current_user), from_at: datetime | None = None, to_at: datetime | None = None, person_id: str | None = None) -> list[EventOut]:
    stmt = select(Event).where(Event.owner_id == user.id)
    if from_at:
        stmt = stmt.where(Event.starts_at >= from_at)
    if to_at:
        stmt = stmt.where(Event.starts_at <= to_at)
    if person_id:
        stmt = stmt.join(EventParticipant).where(EventParticipant.person_id == person_id, EventParticipant.owner_id == user.id)
    return [event_output(db, event, user.id) for event in db.scalars(stmt.order_by(Event.starts_at)).all()]


@router.patch("/api/events/{event_id}", response_model=EventOut)
def event_update(event_id: str, data: EventPatch, db: Session = Depends(get_db), user: User = Depends(current_user)) -> EventOut:
    event = db.scalar(select(Event).where(Event.id == event_id, Event.owner_id == user.id))
    if event is None:
        raise HTTPException(status_code=404, detail="Termin nicht gefunden")
    changes = data.model_dump(exclude_unset=True)
    participant_ids = changes.pop("participant_ids", None)
    previous_start = event.starts_at
    starts_at = changes.get("starts_at", previous_start)
    if participant_ids is not None:
        participant_ids = list(dict.fromkeys(participant_ids))
    if "starts_at" in changes and "ends_at" not in changes and event.ends_at is not None:
        changes["ends_at"] = utc_datetime(event.ends_at) + (utc_datetime(starts_at) - utc_datetime(previous_start))
    ends_at = changes.get("ends_at", event.ends_at)
    if ends_at is not None and utc_datetime(ends_at) < utc_datetime(starts_at):
        raise HTTPException(status_code=422, detail="Das Ende muss nach dem Beginn liegen")
    source_memory_id = changes.get("source_memory_id", event.source_memory_id)
    if source_memory_id and db.scalar(select(Memory.id).where(Memory.id == source_memory_id, Memory.owner_id == user.id)) is None:
        raise HTTPException(status_code=404, detail="Quellerinnerung nicht gefunden")
    if participant_ids is not None:
        valid_ids = set(db.scalars(select(Person.id).where(Person.owner_id == user.id, Person.id.in_(participant_ids))).all())
        if valid_ids != set(participant_ids):
            raise HTTPException(status_code=404, detail="Mindestens eine beteiligte Person wurde nicht gefunden")
    for field, value in changes.items():
        setattr(event, field, value)
    if participant_ids is not None:
        db.query(EventParticipant).filter(EventParticipant.event_id == event.id, EventParticipant.owner_id == user.id).delete(synchronize_session=False)
        db.add_all(EventParticipant(event_id=event.id, person_id=person_id, owner_id=user.id) for person_id in participant_ids)
    reminder = db.scalar(select(Reminder).where(Reminder.event_id == event.id, Reminder.owner_id == user.id))
    if reminder is not None:
        if event.record_type == "experience":
            reminder.state = "done"
        else:
            reminder.title = event.title
        if event.record_type == "appointment" and utc_datetime(starts_at) != utc_datetime(previous_start):
            reminder.due_at = starts_at
            reminder.state = "scheduled"
            reminder.snoozed_until = None
    db.commit()
    db.refresh(event)
    return event_output(db, event, user.id)


@router.delete("/api/events/{event_id}", status_code=204)
def event_delete(event_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    event = db.scalar(select(Event).where(Event.id == event_id, Event.owner_id == user.id))
    if event is None:
        raise HTTPException(status_code=404, detail="Termin nicht gefunden")
    attachment_paths = attachment_files_for_resource(db, user.id, "event", event.id)
    photo_paths=event_photo_files(db,user.id,event.id)
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="events", resource_id=event.id, source="web"))
    db.delete(event)
    db.commit()
    remove_attachment_files(attachment_paths+photo_paths)


@router.post("/api/reminders", response_model=ReminderOut, status_code=201)
def reminder_create(data: ReminderIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Reminder:
    if bool(data.task_id) == bool(data.event_id):
        raise HTTPException(status_code=422, detail="Eine Erinnerung muss genau einer Aufgabe oder einem Termin zugeordnet sein")
    if data.task_id and db.scalar(select(Task.id).where(Task.id == data.task_id, Task.owner_id == user.id)) is None:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
    if data.event_id and db.scalar(select(Event.id).where(Event.id == data.event_id, Event.owner_id == user.id)) is None:
        raise HTTPException(status_code=404, detail="Termin nicht gefunden")
    row = Reminder(owner_id=user.id, **data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/api/reminders", response_model=list[ReminderOut])
def reminder_list(db: Session = Depends(get_db), user: User = Depends(current_user), state: str | None = None) -> list[Reminder]:
    stmt = select(Reminder).where(Reminder.owner_id == user.id)
    if state:
        stmt = stmt.where(Reminder.state == state)
    return list(db.scalars(stmt.order_by(Reminder.due_at)).all())


@router.get("/api/notifications", response_model=list[ReminderOut])
def notifications(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Reminder]:
    now = datetime.now(timezone.utc)
    if is_quiet_hours(user, now):
        return []
    stmt = select(Reminder).where(Reminder.owner_id == user.id, Reminder.state == "scheduled", or_(and_(Reminder.snoozed_until.is_(None), Reminder.due_at <= now), Reminder.snoozed_until <= now))
    return list(db.scalars(stmt.order_by(Reminder.due_at)).all())


@router.patch("/api/reminders/{reminder_id}", response_model=ReminderOut)
def reminder_update(reminder_id: str, data: ReminderAction, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Reminder:
    if data.state not in {"scheduled", "done", "muted"}:
        raise HTTPException(status_code=422, detail="Ungültiger Erinnerungsstatus")
    row = db.scalar(select(Reminder).where(Reminder.id == reminder_id, Reminder.owner_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Erinnerung nicht gefunden")
    row.state = data.state
    row.snoozed_until = data.snoozed_until
    if data.snoozed_until:
        row.state = "scheduled"
    if data.state == "done" and row.contact_person_id:
        person = owned_person(db, row.contact_person_id, user)
        person.last_contact_at = datetime.now(timezone.utc)
        sync_contact_followup(db, person, user, reactivate_muted=True)
    db.commit()
    db.refresh(row)
    return row
