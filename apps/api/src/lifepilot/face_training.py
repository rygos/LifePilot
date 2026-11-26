"""Voluntary photo flashcards; no face analysis or automated identification."""
from datetime import datetime, timedelta, timezone
from typing import Literal
from pathlib import Path
from fastapi.responses import FileResponse
from lifepilot.config import settings

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lifepilot.commitment_routes import persist
from lifepilot.db import get_db
from lifepilot.models import FaceTrainingCard, Person, User
from lifepilot.security import current_user

router = APIRouter(prefix="/api/training/faces", tags=["Namenstraining"])
Rating = Literal["again", "hard", "good", "easy"]
DAYS = (0, 1, 3, 7, 14, 30, 60, 90)
MAX_CARDS = 500


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def now():
    return datetime.now(timezone.utc)


class Enrollment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person_id: str
    active: bool = True


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Rating
    revision: int = Field(ge=0)


class CardOut(BaseModel):
    id: str
    person_id: str
    name: str
    nickname: str | None
    context: str
    active: bool
    available: bool
    photo_changed: bool
    level: int
    review_count: int
    revision: int
    due_at: datetime
    last_review_at: datetime | None
    due: bool


def output(card, person, current):
    available = bool(person.photo_key and not person.is_self and card.photo_key == person.photo_key)
    return CardOut(id=card.id, person_id=person.id, name=" ".join(filter(None,(person.first_name,person.last_name))),
        nickname=person.nickname, context=" · ".join(filter(None,(person.organization,person.job_title,person.how_met)))[:1000],
        active=card.active, available=available, photo_changed=bool(person.photo_key and card.photo_key != person.photo_key),
        level=card.level, review_count=card.review_count, revision=card.revision, due_at=utc(card.due_at),
        last_review_at=utc(card.last_review_at) if card.last_review_at else None,
        due=card.active and available and utc(card.due_at)<=current)


def list_cards(db, owner, due_only=False, limit=100, offset=0):
    if not 1<=limit<=500 or not 0<=offset<=MAX_CARDS:
        raise HTTPException(422,"Ungültige Seitengröße")
    current=now()
    stmt=select(FaceTrainingCard,Person).join(Person,Person.id==FaceTrainingCard.person_id).where(
        FaceTrainingCard.owner_id==owner,Person.owner_id==owner,Person.is_self.is_(False))
    if due_only:
        stmt=stmt.where(FaceTrainingCard.active.is_(True),Person.photo_key==FaceTrainingCard.photo_key,FaceTrainingCard.due_at<=current)
    return [output(card,person,current) for card,person in db.execute(stmt.order_by(FaceTrainingCard.due_at,FaceTrainingCard.id).limit(limit).offset(offset))]


def enroll(db, owner, data, source="web"):
    # Serialize enrollment per account and lock person before training card.
    db.scalar(select(User.id).where(User.id==owner).with_for_update())
    person=db.scalar(select(Person).where(Person.id==data.person_id,Person.owner_id==owner,Person.is_self.is_(False)).with_for_update().execution_options(populate_existing=True))
    if person is None:
        raise HTTPException(404,"Person nicht gefunden")
    card=db.scalar(select(FaceTrainingCard).where(FaceTrainingCard.owner_id==owner,FaceTrainingCard.person_id==person.id).with_for_update().execution_options(populate_existing=True))
    current=now()
    if data.active and not person.photo_key:
        raise HTTPException(422,"Person benötigt ein vorhandenes Kontaktfoto")
    if card is None:
        if not data.active:
            raise HTTPException(404,"Lernkarte nicht gefunden")
        count=db.scalar(select(func.count()).select_from(FaceTrainingCard).where(FaceTrainingCard.owner_id==owner))
        if count>=MAX_CARDS:
            raise HTTPException(409,"Maximal 500 Lernkarten pro Konto")
        card=FaceTrainingCard(owner_id=owner,person_id=person.id,photo_key=person.photo_key,due_at=current)
        persist(db,card,"create",source)
    else:
        changed=data.active and card.photo_key!=person.photo_key
        if card.active!=data.active or changed:
            card.active=data.active
            card.revision+=1
            if changed:
                card.photo_key=person.photo_key
                card.level=card.review_count=0
                card.last_review_at=None
                card.due_at=current
            persist(db,card,"update",source)
    return output(card,person,current)


def review_card(db, owner, card_id, data, source="web"):
    person=db.scalar(select(Person).join(FaceTrainingCard,FaceTrainingCard.person_id==Person.id).where(
        FaceTrainingCard.id==card_id,FaceTrainingCard.owner_id==owner,Person.owner_id==owner,Person.is_self.is_(False)).with_for_update(of=Person).execution_options(populate_existing=True))
    if person is None:
        raise HTTPException(404,"Lernkarte nicht gefunden")
    card=db.scalar(select(FaceTrainingCard).where(FaceTrainingCard.id==card_id,FaceTrainingCard.owner_id==owner).with_for_update().execution_options(populate_existing=True))
    if card is None:
        raise HTTPException(404,"Lernkarte nicht gefunden")
    current=now()
    if card.revision!=data.revision or not card.active or not person.photo_key or person.photo_key!=card.photo_key or utc(card.due_at)>current:
        raise HTTPException(409,"Lernkarte nicht mehr fällig oder geändert. Bitte aktualisieren.")
    if data.rating=="again":
        card.level=0
        interval=timedelta(minutes=10)
    elif data.rating=="hard":
        card.level=max(0,card.level-1)
        interval=timedelta(days=1)
    else:
        card.level=min(7,card.level+(2 if data.rating=="easy" else 1))
        interval=timedelta(days=DAYS[card.level])
    card.due_at=current+interval
    card.last_review_at=current
    card.review_count+=1
    card.revision+=1
    persist(db,card,"update",source)
    return output(card,person,current)


@router.get("",response_model=list[CardOut])
def get_cards(due_only: bool=False,limit: int=Query(100,ge=1,le=500),offset: int=Query(0,ge=0,le=MAX_CARDS),db: Session=Depends(get_db),user: User=Depends(current_user)):
    return list_cards(db,user.id,due_only,limit,offset)


@router.post("/enroll",response_model=CardOut)
def post_enroll(data: Enrollment,db: Session=Depends(get_db),user: User=Depends(current_user)):
    return enroll(db,user.id,data)


@router.get("/{card_id}/photo")
def get_photo(card_id: str, revision: int=Query(ge=0), db: Session=Depends(get_db),user: User=Depends(current_user)):
    pair=db.execute(select(FaceTrainingCard,Person).join(Person,Person.id==FaceTrainingCard.person_id).where(
        FaceTrainingCard.id==card_id,FaceTrainingCard.owner_id==user.id,Person.owner_id==user.id,Person.is_self.is_(False))).first()
    if pair is None:
        raise HTTPException(404,"Lernkarte nicht gefunden")
    card,person=pair
    if card.revision!=revision or not card.active or not person.photo_key or card.photo_key!=person.photo_key:
        raise HTTPException(409,"Lernkarte wurde geändert")
    directory=Path(settings.data_dir)/"people"
    path=directory/card.photo_key
    if path.parent!=directory or not path.is_file():
        raise HTTPException(404,"Kontaktfoto nicht verfügbar")
    return FileResponse(path,media_type="image/jpeg",headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"})


@router.post("/{card_id}/review",response_model=CardOut)
def post_review(card_id: str,data: Review,db: Session=Depends(get_db),user: User=Depends(current_user)):
    return review_card(db,user.id,card_id,data)
