"""Explicitly recorded places and place-related memories; no tracking."""
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from lifepilot.commitment_routes import owned, persist
from lifepilot.db import get_db
from lifepilot.models import AuditEvent, Conversation, Event, Memory, Person, Place, PlaceEntry, User
from lifepilot.security import current_user
from lifepilot.trash_routes import move_to_trash

router = APIRouter(prefix="/api/places", tags=["Ortsgedächtnis"])
EntryKind = Literal["visit", "meeting", "recommendation", "memory", "reference"]


class PlaceIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=240)
    category: str = Field(default="", max_length=120)
    address: str = Field(default="", max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    notes: str = Field(default="", max_length=10000)

    @model_validator(mode="after")
    def coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Breiten- und Längengrad gemeinsam angeben")
        return self


class PlaceOut(PlaceIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    archived: bool
    created_at: datetime


class ArchiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    archived: bool


class EntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: EntryKind
    title: str = Field(min_length=1, max_length=240)
    notes: str = Field(default="", max_length=10000)
    occurred_on: date | None = None
    person_id: str | None = None
    event_id: str | None = None
    conversation_id: str | None = None
    memory_id: str | None = None


class EntryOut(EntryIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    place_id: str
    created_at: datetime


def list_places(db, owner, q=None, archived=False, person_id=None, limit=50, offset=0):
    if not 1 <= limit <= 100 or offset < 0 or (q is not None and len(q)>200):
        raise HTTPException(422,"Ungültige Suchparameter")
    stmt=select(Place).where(Place.owner_id==owner,Place.archived==archived)
    if q and q.strip():
        term=q.strip()
        stmt=stmt.where(or_(Place.name.icontains(term,autoescape=True),Place.category.icontains(term,autoescape=True),Place.address.icontains(term,autoescape=True),Place.notes.icontains(term,autoescape=True),
            select(PlaceEntry.id).where(PlaceEntry.owner_id==owner,PlaceEntry.place_id==Place.id,or_(PlaceEntry.title.icontains(term,autoescape=True),PlaceEntry.notes.icontains(term,autoescape=True))).exists()))
    if person_id:
        owned(db,Person,owner,person_id)
        stmt=stmt.where(select(PlaceEntry.id).where(PlaceEntry.owner_id==owner,PlaceEntry.place_id==Place.id,PlaceEntry.person_id==person_id).exists())
    return [PlaceOut.model_validate(row).model_dump(mode="json") for row in db.scalars(stmt.order_by(Place.name,Place.id).limit(limit).offset(offset))]


def lock_place(db,owner,place_id):
    row=db.scalar(select(Place).where(Place.id==place_id,Place.owner_id==owner).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404,"Ort nicht gefunden")
    return row


def get_place(db,owner,place_id):
    return PlaceOut.model_validate(owned(db,Place,owner,place_id)).model_dump(mode="json")


def create_place(db,owner,data,source="web"):
    return PlaceOut.model_validate(persist(db,Place(owner_id=owner,**data.model_dump()),"create",source)).model_dump(mode="json")


def update_place(db,owner,place_id,data,source="web"):
    row=lock_place(db,owner,place_id)
    for field,value in data.model_dump().items():
        setattr(row,field,value)
    return PlaceOut.model_validate(persist(db,row,"update",source)).model_dump(mode="json")


def archive_place(db,owner,place_id,archived,source="web"):
    row=lock_place(db,owner,place_id)
    row.archived=archived
    return PlaceOut.model_validate(persist(db,row,"update",source)).model_dump(mode="json")


def list_entries(db,owner,place_id,kind=None,limit=50,offset=0):
    owned(db,Place,owner,place_id)
    if not 1<=limit<=100 or offset<0:
        raise HTTPException(422,"Ungültige Seitengröße")
    stmt=select(PlaceEntry).where(PlaceEntry.owner_id==owner,PlaceEntry.place_id==place_id)
    if kind:
        stmt=stmt.where(PlaceEntry.kind==kind)
    return [EntryOut.model_validate(row).model_dump(mode="json") for row in db.scalars(stmt.order_by(PlaceEntry.occurred_on.desc().nullslast(),PlaceEntry.created_at.desc(),PlaceEntry.id).limit(limit).offset(offset))]


def validate_entry_links(db,owner,data):
    for field,model in (("person_id",Person),("event_id",Event),("conversation_id",Conversation),("memory_id",Memory)):
        value=getattr(data,field)
        if value is not None:
            owned(db,model,owner,value)


def create_entry(db,owner,place_id,data,source="web"):
    place=lock_place(db,owner,place_id)
    if place.archived:
        raise HTTPException(409,"Archivierten Ort zuerst reaktivieren")
    validate_entry_links(db,owner,data)
    return EntryOut.model_validate(persist(db,PlaceEntry(owner_id=owner,place_id=place.id,**data.model_dump()),"create",source)).model_dump(mode="json")


def remove_entry(db,owner,place_id,entry_id,source="web"):
    lock_place(db,owner,place_id)
    row=db.scalar(select(PlaceEntry).where(PlaceEntry.owner_id==owner,PlaceEntry.place_id==place_id,PlaceEntry.id==entry_id).with_for_update())
    if row is None:
        raise HTTPException(404,"Ortseintrag nicht gefunden")
    move_to_trash(db,owner,PlaceEntry,entry_id,source)
    db.commit()


def remove_place(db,owner,place_id,source="web"):
    row=lock_place(db,owner,place_id)
    move_to_trash(db,owner,Place,place_id,source)
    db.commit()


@router.get("")
def places(q:str|None=Query(None,max_length=200),archived:bool=False,person_id:str|None=None,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),db:Session=Depends(get_db),user:User=Depends(current_user)):
    return list_places(db,user.id,q,archived,person_id,limit,offset)


@router.post("",status_code=201)
def create(data:PlaceIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return create_place(db,user.id,data)


@router.get("/{place_id}")
def detail(place_id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return get_place(db,user.id,place_id)


@router.put("/{place_id}")
def update(place_id:str,data:PlaceIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return update_place(db,user.id,place_id,data)


@router.patch("/{place_id}/archive")
def archive(place_id:str,data:ArchiveIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return archive_place(db,user.id,place_id,data.archived)


@router.get("/{place_id}/entries")
def entries(place_id:str,kind:EntryKind|None=None,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),db:Session=Depends(get_db),user:User=Depends(current_user)):
    return list_entries(db,user.id,place_id,kind,limit,offset)


@router.post("/{place_id}/entries",status_code=201)
def entry(place_id:str,data:EntryIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return create_entry(db,user.id,place_id,data)


@router.delete("/{place_id}/entries/{entry_id}",status_code=204)
def delete_entry(place_id:str,entry_id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    remove_entry(db,user.id,place_id,entry_id)


@router.delete("/{place_id}",status_code=204)
def delete_place(place_id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    remove_place(db,user.id,place_id)
