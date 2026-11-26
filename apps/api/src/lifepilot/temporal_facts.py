"""Explicitly reviewed person facts with day-level validity and evidence."""
from datetime import date, datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.models import Capture, Person, TemporalFact, User
from lifepilot.commitment_routes import persist
from lifepilot.security import current_user

router = APIRouter(prefix="/api/facts", tags=["Zeitliche Fakten"])
Status = Literal["proposed", "confirmed", "rejected"]
Confidence = Literal["low", "medium", "high"]


class FactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person_id: str
    predicate: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=5000)
    valid_from: date | None = None
    valid_until: date | None = None
    confidence: Confidence = "medium"
    source_note: str = Field(default="", max_length=5000)
    source_capture_id: str | None = None
    source_quote: str | None = Field(default=None, max_length=4000)

    @field_validator("predicate", "value")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Bitte einen konkreten Wert eingeben")
        return value.strip()

    @field_validator("predicate")
    @classmethod
    def normalize_predicate(cls, value):
        return " ".join(value.casefold().split())

    @model_validator(mode="after")
    def valid_period(self):
        if self.valid_from and self.valid_until and self.valid_from >= self.valid_until:
            raise ValueError("Das exklusive Enddatum muss nach dem Beginn liegen")
        if bool(self.source_capture_id) != bool(self.source_quote and self.source_quote.strip()):
            raise ValueError("Erfassungs-ID und wörtliches Quellenzitat müssen gemeinsam angegeben werden")
        return self


class FactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    person_id: str
    predicate: str
    value: str
    valid_from: date | None
    valid_until: date | None
    confidence: Confidence
    status: Status
    source_note: str
    source_capture_id: str | None
    source_quote: str | None
    created_at: datetime
    updated_at: datetime


class FactState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status


class FactEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valid_until: date


def owned_fact(db, owner, fact_id, lock=False):
    stmt = select(TemporalFact).where(TemporalFact.owner_id == owner, TemporalFact.id == fact_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(404, "Fakt nicht gefunden")
    return row


def list_facts(db, owner, person_id=None, predicate=None, status=None, as_of=None, limit=100, offset=0):
    stmt = select(TemporalFact).where(TemporalFact.owner_id == owner)
    if person_id is not None:
        if db.scalar(select(Person.id).where(Person.owner_id == owner, Person.id == person_id)) is None:
            raise HTTPException(404, "Person nicht gefunden")
        stmt = stmt.where(TemporalFact.person_id == person_id)
    if predicate is not None:
        stmt = stmt.where(TemporalFact.predicate == " ".join(predicate.casefold().split()))
    if status is not None:
        stmt = stmt.where(TemporalFact.status == status)
    if as_of is not None:
        # Unknown bounds are possible matches, not proof of validity.
        stmt = stmt.where(or_(TemporalFact.valid_from.is_(None), TemporalFact.valid_from <= as_of),
                          or_(TemporalFact.valid_until.is_(None), TemporalFact.valid_until > as_of))
    return list(db.scalars(stmt.order_by(TemporalFact.valid_from.desc().nullslast(), TemporalFact.created_at.desc(), TemporalFact.id).limit(limit).offset(offset)))


def create_fact(db, owner, data: FactIn, source="web"):
    if db.scalar(select(Person.id).where(Person.owner_id == owner, Person.id == data.person_id)) is None:
        raise HTTPException(404, "Person nicht gefunden")
    if data.source_capture_id:
        capture = db.scalar(select(Capture).where(Capture.owner_id == owner, Capture.id == data.source_capture_id))
        if capture is None:
            raise HTTPException(404, "Quellerfassung nicht gefunden")
        if data.source_quote not in capture.original_text:
            raise HTTPException(422, "Quellenzitat muss wörtlich in der Erfassung enthalten sein")
    return persist(db, TemporalFact(owner_id=owner, **data.model_dump(), status="proposed"), "create", source)


def set_fact_status(db, owner, fact_id, status: Status, source="web"):
    row = owned_fact(db, owner, fact_id, True)
    if row.status == status:
        return row
    row.status = status
    return persist(db, row, "update", source)


def end_fact(db, owner, fact_id, until: date, source="web"):
    row = owned_fact(db, owner, fact_id, True)
    if row.status != "confirmed":
        raise HTTPException(409, "Nur bestätigte Fakten können zeitlich beendet werden")
    if row.valid_from is not None and until <= row.valid_from:
        raise HTTPException(422, "Enddatum muss nach Beginn liegen")
    if row.valid_until is not None and row.valid_until != until:
        raise HTTPException(409, "Fakt hat bereits ein Enddatum; bei Fehlern ablehnen und korrigierten Fakt anlegen")
    if row.valid_until == until:
        return row
    row.valid_until = until
    return persist(db, row, "update", source)


def person_current_facts(db, user, person_id):
    today = datetime.now(timezone.utc).astimezone(ZoneInfo(user.timezone_name)).date()
    return [FactOut.model_validate(row).model_dump(mode="json") for row in list_facts(db, user.id, person_id, status="confirmed", as_of=today, limit=50)]


@router.get("", response_model=list[FactOut])
def get_facts(person_id: str | None = None, predicate: str | None = None, status: Status | None = None, as_of: date | None = None, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db), user: User = Depends(current_user)):
    return list_facts(db, user.id, person_id, predicate, status, as_of, limit, offset)


@router.post("", response_model=FactOut, status_code=201)
def post_fact(data: FactIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return create_fact(db, user.id, data)


@router.patch("/{fact_id}/status", response_model=FactOut)
def patch_status(fact_id: str, data: FactState, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return set_fact_status(db, user.id, fact_id, data.status)


@router.patch("/{fact_id}/end", response_model=FactOut)
def patch_end(fact_id: str, data: FactEnd, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return end_fact(db, user.id, fact_id, data.valid_until)
