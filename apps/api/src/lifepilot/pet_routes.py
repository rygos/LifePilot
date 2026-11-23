from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.models import AuditEvent, Event, Pet, PetEvent, PetPerson, Person, User
from lifepilot.schemas import PetIn, PetOut, PetPatch, PetPersonLinkIn, PetPersonLinkOut
from lifepilot.security import current_user

router = APIRouter(prefix="/api/pets", tags=["pets"])


def _pet_outputs(db: Session, rows: list[Pet], owner_id: str) -> list[PetOut]:
    if not rows:
        return []
    pet_ids = [row.id for row in rows]
    links: dict[str, list[PetPersonLinkOut]] = {pet_id: [] for pet_id in pet_ids}
    event_ids: dict[str, list[str]] = {pet_id: [] for pet_id in pet_ids}
    for link in db.scalars(select(PetPerson).where(PetPerson.owner_id == owner_id, PetPerson.pet_id.in_(pet_ids)).order_by(PetPerson.relationship_type, PetPerson.person_id)).all():
        links[link.pet_id].append(PetPersonLinkOut(person_id=link.person_id, relationship_type=link.relationship_type))
    for link in db.scalars(select(PetEvent).where(PetEvent.owner_id == owner_id, PetEvent.pet_id.in_(pet_ids)).order_by(PetEvent.event_id)).all():
        event_ids[link.pet_id].append(link.event_id)
    return [PetOut(id=row.id, name=row.name, species=row.species, breed=row.breed, sex=row.sex, birthday=row.birthday, is_neutered=row.is_neutered, notes=row.notes, person_links=links[row.id], event_ids=event_ids[row.id], created_at=row.created_at, updated_at=row.updated_at) for row in rows]


def _validate_links(db: Session, owner: User, person_links: list[PetPersonLinkIn] | None, event_ids: list[str] | None) -> None:
    if person_links is not None:
        person_ids = [link.person_id for link in person_links]
        if len(person_ids) != len(set(person_ids)):
            raise HTTPException(status_code=422, detail="Eine Person darf nicht mehrfach mit demselben Tier verknüpft werden")
        if person_ids:
            found = set(db.scalars(select(Person.id).where(Person.owner_id == owner.id, Person.id.in_(person_ids))).all())
            if found != set(person_ids):
                raise HTTPException(status_code=404, detail="Mindestens eine verknüpfte Person wurde nicht gefunden")
    if event_ids is not None:
        if len(event_ids) != len(set(event_ids)):
            raise HTTPException(status_code=422, detail="Ein Ereignis darf nicht mehrfach verknüpft werden")
        if event_ids:
            found = set(db.scalars(select(Event.id).where(Event.owner_id == owner.id, Event.id.in_(event_ids))).all())
            if found != set(event_ids):
                raise HTTPException(status_code=404, detail="Mindestens ein verknüpftes Ereignis wurde nicht gefunden")


def _set_links(db: Session, row: Pet, owner_id: str, person_links: list[PetPersonLinkIn] | None, event_ids: list[str] | None) -> None:
    if person_links is not None:
        db.execute(delete(PetPerson).where(PetPerson.pet_id == row.id, PetPerson.owner_id == owner_id))
        db.add_all(PetPerson(pet_id=row.id, person_id=link.person_id, owner_id=owner_id, relationship_type=link.relationship_type) for link in person_links)
    if event_ids is not None:
        db.execute(delete(PetEvent).where(PetEvent.pet_id == row.id, PetEvent.owner_id == owner_id))
        db.add_all(PetEvent(pet_id=row.id, event_id=event_id, owner_id=owner_id) for event_id in event_ids)


def pet_list(db: Session, owner: User, query: str = "") -> list[PetOut]:
    stmt = select(Pet).where(Pet.owner_id == owner.id)
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(or_(Pet.name.ilike(pattern), Pet.species.ilike(pattern), Pet.breed.ilike(pattern), Pet.notes.ilike(pattern)))
    rows = list(db.scalars(stmt.order_by(Pet.name, Pet.id)).all())
    return _pet_outputs(db, rows, owner.id)


def pet_get(db: Session, owner: User, pet_id: str) -> PetOut:
    row = db.scalar(select(Pet).where(Pet.id == pet_id, Pet.owner_id == owner.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Tier nicht gefunden")
    return _pet_outputs(db, [row], owner.id)[0]


def pet_create(db: Session, owner: User, data: PetIn, source: str = "web") -> PetOut:
    _validate_links(db, owner, data.person_links, data.event_ids)
    row = Pet(owner_id=owner.id, **data.model_dump(exclude={"person_links", "event_ids"}))
    db.add(row)
    db.flush()
    _set_links(db, row, owner.id, data.person_links, data.event_ids)
    db.add(AuditEvent(owner_id=owner.id, action="create", resource_type="pets", resource_id=row.id, source=source))
    db.commit()
    db.refresh(row)
    return _pet_outputs(db, [row], owner.id)[0]


def pet_update(db: Session, owner: User, pet_id: str, data: PetPatch, source: str = "web") -> PetOut:
    row = db.scalar(select(Pet).where(Pet.id == pet_id, Pet.owner_id == owner.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Tier nicht gefunden")
    _validate_links(db, owner, data.person_links, data.event_ids)
    changes = data.model_dump(exclude_unset=True, exclude={"person_links", "event_ids"})
    for key, value in changes.items():
        setattr(row, key, value)
    _set_links(db, row, owner.id, data.person_links, data.event_ids)
    db.add(AuditEvent(owner_id=owner.id, action="update", resource_type="pets", resource_id=row.id, source=source))
    db.commit()
    db.refresh(row)
    return _pet_outputs(db, [row], owner.id)[0]


def pet_delete(db: Session, owner: User, pet_id: str, source: str = "web") -> None:
    row = db.scalar(select(Pet).where(Pet.id == pet_id, Pet.owner_id == owner.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Tier nicht gefunden")
    db.add(AuditEvent(owner_id=owner.id, action="delete", resource_type="pets", resource_id=row.id, source=source))
    db.delete(row)
    db.commit()


@router.get("", response_model=list[PetOut])
def pet_list_route(q: str = "", db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[PetOut]:
    return pet_list(db, user, q.strip())


@router.post("", response_model=PetOut, status_code=201)
def pet_create_route(data: PetIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> PetOut:
    return pet_create(db, user, data)


@router.get("/{pet_id}", response_model=PetOut)
def pet_get_route(pet_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> PetOut:
    return pet_get(db, user, pet_id)


@router.patch("/{pet_id}", response_model=PetOut)
def pet_update_route(pet_id: str, data: PetPatch, db: Session = Depends(get_db), user: User = Depends(current_user)) -> PetOut:
    return pet_update(db, user, pet_id, data)


@router.delete("/{pet_id}", status_code=204)
def pet_delete_route(pet_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    pet_delete(db, user, pet_id)
