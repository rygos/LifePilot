from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.models import AuditEvent, Event, JournalEntry, JournalEntryEvent, JournalEntryPerson, JournalEntryProject, Person, Project, User
from lifepilot.schemas import JournalEntryIn, JournalEntryOut, JournalEntryPatch
from lifepilot.security import current_user

router = APIRouter(prefix="/api/journal", tags=["journal"])


def _entry_outputs(db: Session, rows: list[JournalEntry], owner_id: str) -> list[JournalEntryOut]:
    if not rows:
        return []
    entry_ids = [row.id for row in rows]
    people: dict[str, list[str]] = {entry_id: [] for entry_id in entry_ids}
    projects: dict[str, list[str]] = {entry_id: [] for entry_id in entry_ids}
    events: dict[str, list[str]] = {entry_id: [] for entry_id in entry_ids}
    for link in db.scalars(select(JournalEntryPerson).where(JournalEntryPerson.owner_id == owner_id, JournalEntryPerson.entry_id.in_(entry_ids))).all():
        people[link.entry_id].append(link.person_id)
    for link in db.scalars(select(JournalEntryProject).where(JournalEntryProject.owner_id == owner_id, JournalEntryProject.entry_id.in_(entry_ids))).all():
        projects[link.entry_id].append(link.project_id)
    for link in db.scalars(select(JournalEntryEvent).where(JournalEntryEvent.owner_id == owner_id, JournalEntryEvent.entry_id.in_(entry_ids))).all():
        events[link.entry_id].append(link.event_id)
    return [JournalEntryOut(id=row.id, entry_date=row.entry_date, title=row.title, content=row.content, mood=row.mood, person_ids=people[row.id], project_ids=projects[row.id], event_ids=events[row.id], created_at=row.created_at, updated_at=row.updated_at) for row in rows]


def _validate_links(db: Session, owner: User, data: JournalEntryIn | JournalEntryPatch) -> None:
    for ids, model, label in ((data.person_ids, Person, "Person"), (data.project_ids, Project, "Projekt"), (data.event_ids, Event, "Ereignis")):
        if ids is None:
            continue
        if len(ids) != len(set(ids)):
            raise HTTPException(status_code=422, detail=f"Ein {label} darf nicht mehrfach verknüpft werden")
        if ids:
            found = set(db.scalars(select(model.id).where(model.owner_id == owner.id, model.id.in_(ids))).all())
            if found != set(ids):
                raise HTTPException(status_code=404, detail=f"Mindestens ein verknüpftes {label} wurde nicht gefunden")


def _set_links(db: Session, row: JournalEntry, owner_id: str, data: JournalEntryIn | JournalEntryPatch) -> None:
    for field, key, link_model in (
        ("person_ids", "person_id", JournalEntryPerson),
        ("project_ids", "project_id", JournalEntryProject),
        ("event_ids", "event_id", JournalEntryEvent),
    ):
        ids = getattr(data, field)
        if ids is None:
            continue
        db.execute(delete(link_model).where(link_model.entry_id == row.id, link_model.owner_id == owner_id))
        db.add_all(link_model(entry_id=row.id, owner_id=owner_id, **{key: item_id}) for item_id in ids)


def journal_list(db: Session, owner: User, from_date: date | None = None, to_date: date | None = None, q: str = "", limit: int = 100) -> list[JournalEntryOut]:
    if from_date is not None and to_date is not None and from_date > to_date:
        raise ValueError("Der Beginn muss vor dem Ende liegen")
    stmt = select(JournalEntry).where(JournalEntry.owner_id == owner.id)
    if from_date is not None:
        stmt = stmt.where(JournalEntry.entry_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(JournalEntry.entry_date <= to_date)
    if q:
        stmt = stmt.where(or_(JournalEntry.title.ilike(f"%{q}%"), JournalEntry.content.ilike(f"%{q}%")))
    rows = list(db.scalars(stmt.order_by(JournalEntry.entry_date.desc(), JournalEntry.created_at.desc()).limit(limit)).all())
    return _entry_outputs(db, rows, owner.id)


def journal_get(db: Session, owner: User, entry_id: str) -> JournalEntryOut:
    row = db.scalar(select(JournalEntry).where(JournalEntry.id == entry_id, JournalEntry.owner_id == owner.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Tagebucheintrag nicht gefunden")
    return _entry_outputs(db, [row], owner.id)[0]


def journal_create(db: Session, owner: User, data: JournalEntryIn, source: str = "web") -> JournalEntryOut:
    _validate_links(db, owner, data)
    fields = data.model_dump(exclude={"person_ids", "project_ids", "event_ids"})
    row = JournalEntry(owner_id=owner.id, **fields)
    db.add(row)
    db.flush()
    _set_links(db, row, owner.id, data)
    db.add(AuditEvent(owner_id=owner.id, action="create", resource_type="journal_entries", resource_id=row.id, source=source))
    db.commit()
    db.refresh(row)
    return _entry_outputs(db, [row], owner.id)[0]


def journal_update(db: Session, owner: User, entry_id: str, data: JournalEntryPatch, source: str = "web") -> JournalEntryOut:
    row = db.scalar(select(JournalEntry).where(JournalEntry.id == entry_id, JournalEntry.owner_id == owner.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Tagebucheintrag nicht gefunden")
    _validate_links(db, owner, data)
    changes = data.model_dump(exclude_unset=True, exclude={"person_ids", "project_ids", "event_ids"})
    for key, value in changes.items():
        setattr(row, key, value)
    _set_links(db, row, owner.id, data)
    db.add(AuditEvent(owner_id=owner.id, action="update", resource_type="journal_entries", resource_id=row.id, source=source))
    db.commit()
    db.refresh(row)
    return _entry_outputs(db, [row], owner.id)[0]


def journal_delete(db: Session, owner: User, entry_id: str, source: str = "web") -> None:
    row = db.scalar(select(JournalEntry).where(JournalEntry.id == entry_id, JournalEntry.owner_id == owner.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Tagebucheintrag nicht gefunden")
    db.add(AuditEvent(owner_id=owner.id, action="delete", resource_type="journal_entries", resource_id=row.id, source=source))
    db.delete(row)
    db.commit()


@router.get("", response_model=list[JournalEntryOut])
def journal_list_route(db: Session = Depends(get_db), user: User = Depends(current_user), from_date: date | None = None, to_date: date | None = None, q: str = "", limit: int = Query(default=100, ge=1, le=250)) -> list[JournalEntryOut]:
    if from_date is not None and to_date is not None and from_date > to_date:
        raise HTTPException(status_code=422, detail="Der Beginn muss vor dem Ende liegen")
    return journal_list(db, user, from_date, to_date, q.strip(), limit)


@router.post("", response_model=JournalEntryOut, status_code=201)
def journal_create_route(data: JournalEntryIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> JournalEntryOut:
    return journal_create(db, user, data)


@router.get("/{entry_id}", response_model=JournalEntryOut)
def journal_get_route(entry_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> JournalEntryOut:
    return journal_get(db, user, entry_id)


@router.patch("/{entry_id}", response_model=JournalEntryOut)
def journal_update_route(entry_id: str, data: JournalEntryPatch, db: Session = Depends(get_db), user: User = Depends(current_user)) -> JournalEntryOut:
    return journal_update(db, user, entry_id, data)


@router.delete("/{entry_id}", status_code=204)
def journal_delete_route(entry_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    journal_delete(db, user, entry_id)
