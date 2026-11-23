from collections import deque

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.models import Person, Relationship, User
from lifepilot.relationship_language import relationship_category
from lifepilot.security import current_user
from lifepilot.services import owned_person

router = APIRouter()

FAMILY_CATEGORIES = {"parent", "child", "spouse", "partner", "sibling"}


class FamilyTreePerson(BaseModel):
    id: str
    first_name: str
    last_name: str
    nickname: str | None
    gender: str
    birthday: str | None
    birthday_precision: str
    photo_key: str | None


class FamilyTreeRelationship(BaseModel):
    id: str
    source_person_id: str
    target_person_id: str
    relationship_type: str
    inverse_relationship_type: str
    confirmed: bool


class FamilyTreeResponse(BaseModel):
    root_person_id: str
    people: list[FamilyTreePerson]
    relationships: list[FamilyTreeRelationship]


def _family_category(row: Relationship) -> str | None:
    relation = relationship_category(row.relationship_type)
    category = relation[0] if relation else None
    if category not in FAMILY_CATEGORIES:
        inverse = relationship_category(row.inverse_relationship_type)
        inverse_category = inverse[0] if inverse else None
        if inverse_category == "parent":
            category = "child"
        elif inverse_category == "child":
            category = "parent"
        elif inverse_category in {"spouse", "partner", "sibling"}:
            category = inverse_category
    if category not in FAMILY_CATEGORIES:
        return None
    return category


@router.get("/api/people/{person_id}/family-tree", response_model=FamilyTreeResponse)
def family_tree(
    person_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> FamilyTreeResponse:
    owned_person(db, person_id, user)
    rows = db.scalars(select(Relationship).where(Relationship.owner_id == user.id)).all()
    family_rows = [(row, _family_category(row)) for row in rows]
    family_rows = [(row, category) for row, category in family_rows if category is not None]

    connected = {person_id}
    queue = deque([person_id])
    while queue:
        current = queue.popleft()
        for row, _ in family_rows:
            if row.source_person_id == current:
                other = row.target_person_id
            elif row.target_person_id == current:
                other = row.source_person_id
            else:
                continue
            if other not in connected:
                connected.add(other)
                queue.append(other)

    people = db.scalars(
        select(Person).where(Person.owner_id == user.id, Person.id.in_(connected))
    ).all()
    relevant_rows = [row for row, _ in family_rows if row.source_person_id in connected and row.target_person_id in connected]
    return FamilyTreeResponse(
        root_person_id=person_id,
        people=[FamilyTreePerson.model_validate(person, from_attributes=True) for person in sorted(people, key=lambda item: (item.first_name.casefold(), item.last_name.casefold()))],
        relationships=[FamilyTreeRelationship.model_validate(row, from_attributes=True) for row in relevant_rows],
    )
