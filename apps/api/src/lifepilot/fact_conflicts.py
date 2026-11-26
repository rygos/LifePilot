"""Conservative, reviewable detection of overlapping person facts."""
from datetime import datetime
from hashlib import sha256
from typing import Literal
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from lifepilot.db import get_db
from lifepilot.models import AuditEvent, FactConflictDecision, Person, TemporalFact, User
from lifepilot.security import current_user
from lifepilot.temporal_facts import FactOut, owned_fact

router = APIRouter(prefix="/api/facts/conflicts", tags=["Faktenwidersprüche"])
# These fields often describe a changing state, but parallel values can be true.
# Free-form/multi-valued properties (e.g. hobbies) are deliberately not flagged.
PREDICATES = frozenset({"wohnort", "hauptwohnsitz", "arbeitgeber", "arbeitsstelle", "beruf",
                        "beziehungsstatus", "familienstand", "residence", "employer",
                        "job title", "occupation", "relationship status"})
Action = Literal["changed", "both", "reject_a", "reject_b", "defer"]


def version(row):
    return sha256(json.dumps([row.id, row.revision, row.status, row.value_key, str(row.valid_from), str(row.valid_until)]).encode()).hexdigest()


class ConflictOut(BaseModel):
    a: FactOut
    b: FactOut
    a_version: str
    b_version: str
    uncertain_period: bool


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_a_id: str
    fact_b_id: str
    a_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    b_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Action
    previous_fact_id: str | None = None
    note: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def validate_action(self):
        if self.fact_a_id >= self.fact_b_id:
            raise ValueError("Fakten müssen in der angegebenen Reihenfolge A/B übermittelt werden")
        if self.action == "changed":
            if self.previous_fact_id not in (self.fact_a_id, self.fact_b_id):
                raise ValueError("Bitte den früheren Fakt auswählen")
        elif self.previous_fact_id is not None:
            raise ValueError("Früherer Fakt ist nur bei einer zeitlichen Veränderung zulässig")
        return self


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    person_id: str
    fact_a_id: str
    fact_b_id: str
    action: Action
    note: str
    before: dict
    after: dict
    created_at: datetime


def pair_query(owner):
    a, b = aliased(TemporalFact), aliased(TemporalFact)
    coexist = select(FactConflictDecision.id).where(
        FactConflictDecision.owner_id == owner,
        FactConflictDecision.fact_a_id == a.id, FactConflictDecision.fact_b_id == b.id,
        FactConflictDecision.action == "both",
        FactConflictDecision.a_revision == a.revision,
        FactConflictDecision.b_revision == b.revision,
    ).correlate(a, b).exists()
    stmt = select(a, b).join(b, (a.person_id == b.person_id) & (a.predicate == b.predicate) & (a.id < b.id)).where(
        a.owner_id == owner, b.owner_id == owner,
        a.predicate.in_(PREDICATES),
        a.status != "rejected", b.status != "rejected",
        a.value_key != b.value_key,
        or_(a.valid_until.is_(None), b.valid_from.is_(None), a.valid_until > b.valid_from),
        or_(b.valid_until.is_(None), a.valid_from.is_(None), b.valid_until > a.valid_from),
        ~coexist,
    )
    return stmt, a, b


def output(a, b):
    return ConflictOut(a=FactOut.model_validate(a), b=FactOut.model_validate(b),
                       a_version=version(a), b_version=version(b),
                       uncertain_period=any(x is None for x in (a.valid_from, a.valid_until, b.valid_from, b.valid_until)))


def validate_person(db, owner, person_id):
    if person_id is not None and db.scalar(select(Person.id).where(Person.id == person_id, Person.owner_id == owner)) is None:
        raise HTTPException(404, "Person nicht gefunden")


def list_conflicts(db, owner, person_id=None, limit=50, offset=0):
    validate_person(db, owner, person_id)
    stmt, a, b = pair_query(owner)
    if person_id is not None:
        stmt = stmt.where(a.person_id == person_id)
    return [output(left, right) for left, right in db.execute(stmt.order_by(a.person_id, a.predicate, a.id, b.id).offset(offset).limit(limit))]


def snapshot(a, b):
    return {label: {"id": row.id, "predicate": row.predicate, "value": row.value, "status": row.status,
                    "valid_from": row.valid_from.isoformat() if row.valid_from else None,
                    "valid_until": row.valid_until.isoformat() if row.valid_until else None}
            for label, row in (("a", a), ("b", b))}


def resolve_conflict(db, owner, data: ResolveIn, source="web"):
    # Lock in canonical order, including when a competing ordinary fact edit is running.
    a = owned_fact(db, owner, data.fact_a_id, True)
    b = owned_fact(db, owner, data.fact_b_id, True)
    if version(a) != data.a_version or version(b) != data.b_version:
        raise HTTPException(409, "Fakten wurden geändert. Bitte Konflikte neu laden.")
    stmt, left, right = pair_query(owner)
    if db.execute(stmt.where(left.id == a.id, right.id == b.id)).first() is None:
        raise HTTPException(409, "Dieser mögliche Widerspruch ist nicht mehr offen.")
    before = snapshot(a, b)
    if data.action == "changed":
        previous, following = (a, b) if data.previous_fact_id == a.id else (b, a)
        if following.valid_from is None:
            raise HTTPException(422, "Der nachfolgende Fakt benötigt ein bekanntes Beginndatum.")
        if previous.valid_until is not None or (previous.valid_from and following.valid_from <= previous.valid_from):
            raise HTTPException(409, "Der frühere Zeitraum kann nicht automatisch beendet werden. Bitte Fakten einzeln korrigieren.")
        previous.valid_until = following.valid_from
        previous.status = following.status = "confirmed"
    elif data.action == "both":
        a.status = b.status = "confirmed"
    elif data.action == "reject_a":
        a.status, b.status = "rejected", "confirmed"
    elif data.action == "reject_b":
        a.status, b.status = "confirmed", "rejected"
    after = snapshot(a, b)
    for label, row in (("a", a), ("b", b)):
        if before[label] != after[label]:
            row.revision += 1
            db.add(AuditEvent(owner_id=owner, action="update", resource_type="temporal_facts", resource_id=row.id, source=source))
    db.flush()
    decision = FactConflictDecision(owner_id=owner, person_id=a.person_id, fact_a_id=a.id, fact_b_id=b.id,
                                    action=data.action, note=data.note.strip(), a_revision=a.revision,
                                    b_revision=b.revision, before=before, after=after)
    db.add(decision)
    db.flush()
    db.add(AuditEvent(owner_id=owner, action="create", resource_type="fact_conflict_decisions", resource_id=decision.id, source=source))
    db.commit()
    db.refresh(decision)
    return decision


def list_decisions(db, owner, person_id=None, limit=50, offset=0):
    validate_person(db, owner, person_id)
    stmt = select(FactConflictDecision).where(FactConflictDecision.owner_id == owner)
    if person_id is not None:
        stmt = stmt.where(FactConflictDecision.person_id == person_id)
    return list(db.scalars(stmt.order_by(FactConflictDecision.created_at.desc(), FactConflictDecision.id).offset(offset).limit(limit)))


@router.get("", response_model=list[ConflictOut])
def get_conflicts(person_id: str | None = None, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), user: User = Depends(current_user)):
    return list_conflicts(db, user.id, person_id, limit, offset)


@router.post("/resolve", response_model=DecisionOut, status_code=201)
def post_resolution(data: ResolveIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return resolve_conflict(db, user.id, data)


@router.get("/history", response_model=list[DecisionOut])
def get_history(person_id: str | None = None, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), user: User = Depends(current_user)):
    return list_decisions(db, user.id, person_id, limit, offset)
