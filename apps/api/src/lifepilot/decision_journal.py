"""Decision journal: original reasoning is immutable; reviews are appended."""
from datetime import date, datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifepilot.attachment_routes import owned_attachment_resource
from lifepilot.commitment_routes import owned, persist
from lifepilot.db import get_db
from lifepilot.models import Attachment, AuditEvent, DecisionEntry, DecisionReview, Memory, Person, Project, User
from lifepilot.security import current_user

router = APIRouter(prefix="/api/decisions", tags=["Entscheidungsjournal"])
Status = Literal["open", "closed"]
Assessment = Literal["better", "as_expected", "worse", "unclear"]


def local_today(user):
    return datetime.now(timezone.utc).astimezone(ZoneInfo(user.timezone_name)).date()


class Alternative(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=240)
    pros: str = Field(default="", max_length=2000)
    cons: str = Field(default="", max_length=2000)


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=240)
    decided_on: date
    choice: str = Field(min_length=1, max_length=5000)
    rationale: str = Field(min_length=1, max_length=10000)
    alternatives: list[Alternative] = Field(default_factory=list, max_length=10)
    expected_outcome: str = Field(default="", max_length=5000)
    review_on: date | None = None
    person_id: str | None = None
    project_id: str | None = None
    memory_id: str | None = None
    attachment_id: str | None = None

    @model_validator(mode="after")
    def valid_review(self):
        if self.review_on and self.review_on < self.decided_on:
            raise ValueError("Wiedervorlage darf nicht vor der Entscheidung liegen")
        return self


class DecisionOut(DecisionIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: Status
    revision: int
    created_at: datetime


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    revision: int = Field(ge=0)
    assessment: Assessment
    outcome: str = Field(min_length=1, max_length=10000)
    lessons: str = Field(default="", max_length=10000)
    next_review_on: date | None = None
    closed: bool = False

    @model_validator(mode="after")
    def validate_close(self):
        if self.closed and self.next_review_on is not None:
            raise ValueError("Abgeschlossene Entscheidungen haben keine nächste Wiedervorlage")
        return self


class ReviewOut(ReviewIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    reviewed_on: date
    created_at: datetime


def list_entries(db, user, status=None, due_only=False, person_id=None, project_id=None, limit=50, offset=0):
    if not 1<=limit<=100 or offset<0:
        raise HTTPException(422,"Ungültige Seitengröße")
    stmt=select(DecisionEntry).where(DecisionEntry.owner_id==user.id)
    if status:
        stmt=stmt.where(DecisionEntry.status==status)
    if due_only:
        stmt=stmt.where(DecisionEntry.status=="open",DecisionEntry.review_on<=local_today(user))
    for value,model,col in ((person_id,Person,DecisionEntry.person_id),(project_id,Project,DecisionEntry.project_id)):
        if value:
            owned(db,model,user.id,value)
            stmt=stmt.where(col==value)
    order=(DecisionEntry.review_on,DecisionEntry.id) if due_only else (DecisionEntry.decided_on.desc(),DecisionEntry.created_at.desc(),DecisionEntry.id)
    return [DecisionOut.model_validate(row).model_dump(mode="json") for row in db.scalars(stmt.order_by(*order).limit(limit).offset(offset))]


def create_entry(db,user,data,source="web"):
    if data.decided_on>local_today(user):
        raise HTTPException(422,"Entscheidungsdatum darf nicht in der Zukunft liegen")
    for value,model in ((data.person_id,Person),(data.project_id,Project),(data.memory_id,Memory),(data.attachment_id,Attachment)):
        if value:
            row=owned(db,model,user.id,value)
            if model is Attachment:
                owned_attachment_resource(db,row.resource_type,row.resource_id,user)
    row=persist(db,DecisionEntry(owner_id=user.id,**data.model_dump()),"create",source)
    return DecisionOut.model_validate(row).model_dump(mode="json")


def get_entry(db,user,decision_id):
    row=owned(db,DecisionEntry,user.id,decision_id)
    return DecisionOut.model_validate(row).model_dump(mode="json")


def history(db,user,decision_id,limit=50,offset=0):
    owned(db,DecisionEntry,user.id,decision_id)
    if not 1<=limit<=100 or offset<0:
        raise HTTPException(422,"Ungültige Seitengröße")
    stmt=select(DecisionReview).where(DecisionReview.owner_id==user.id,DecisionReview.decision_id==decision_id)
    return [ReviewOut.model_validate(row).model_dump(mode="json") for row in db.scalars(stmt.order_by(DecisionReview.revision.desc()).limit(limit).offset(offset))]


def add_review(db,user,decision_id,data,source="web"):
    row=db.scalar(select(DecisionEntry).where(DecisionEntry.id==decision_id,DecisionEntry.owner_id==user.id).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404,"Entscheidung nicht gefunden")
    if row.revision!=data.revision:
        raise HTTPException(409,"Entscheidung wurde bereits bewertet. Bitte aktualisieren.")
    today=local_today(user)
    if data.next_review_on and data.next_review_on<=today:
        raise HTTPException(422,"Die nächste Wiedervorlage muss in der Zukunft liegen")
    # A further review may reopen a closed entry; original reasoning is never overwritten.
    row.revision+=1
    row.status="closed" if data.closed else "open"
    row.review_on=data.next_review_on
    review=DecisionReview(owner_id=user.id,decision_id=row.id,reviewed_on=today,**data.model_dump(exclude={"revision"}),revision=row.revision)
    db.add(review)
    try:
        db.flush()
        db.add_all([AuditEvent(owner_id=user.id,action="update",resource_type="decision_entries",resource_id=row.id,source=source),
                    AuditEvent(owner_id=user.id,action="create",resource_type="decision_reviews",resource_id=review.id,source=source)])
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,"Konkurrierende Bewertung. Bitte aktualisieren.") from None
    return {"decision":DecisionOut.model_validate(row).model_dump(mode="json"),"review":ReviewOut.model_validate(review).model_dump(mode="json")}


@router.get("")
def entries(status:Status|None=None,due_only:bool=False,person_id:str|None=None,project_id:str|None=None,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),db:Session=Depends(get_db),user:User=Depends(current_user)):
    return list_entries(db,user,status,due_only,person_id,project_id,limit,offset)


@router.post("",status_code=201)
def create(data:DecisionIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return create_entry(db,user,data)


@router.get("/{decision_id}")
def detail(decision_id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return get_entry(db,user,decision_id)


@router.get("/{decision_id}/reviews")
def reviews(decision_id:str,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),db:Session=Depends(get_db),user:User=Depends(current_user)):
    return history(db,user,decision_id,limit,offset)


@router.post("/{decision_id}/reviews",status_code=201)
def review(decision_id:str,data:ReviewIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return add_review(db,user,decision_id,data)
