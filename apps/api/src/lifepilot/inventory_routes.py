"""Explicit inventory, last recorded storage location and maintenance history."""
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifepilot.attachment_routes import owned_attachment_resource
from lifepilot.commitment_routes import owned, persist
from lifepilot.db import get_db
from lifepilot.models import Attachment, AuditEvent, InventoryHistory, InventoryItem, InventoryLoan, Loan, Person, Place, User
from lifepilot.schemas import LoanOut
from lifepilot.security import current_user

router = APIRouter(prefix="/api/inventory", tags=["Gegenstandsverwaltung"])
Ownership = Literal["own","other","unknown"]


def today(user):
    return datetime.now(timezone.utc).astimezone(ZoneInfo(user.timezone_name)).date()


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1,max_length=240)
    category: str = Field(default="",max_length=120)
    serial_number: str = Field(default="",max_length=240)
    ownership: Ownership = "unknown"
    owner_person_id: str | None = None
    purchase_on: date | None = None
    warranty_until: date | None = None
    receipt_attachment_id: str | None = None
    maintenance_interval_days: int | None = Field(default=None,ge=1,le=3650)
    next_maintenance_on: date | None = None
    notes: str = Field(default="",max_length=10000)

    @model_validator(mode="after")
    def consistency(self):
        if self.owner_person_id is not None and self.ownership!="other":
            raise ValueError("Personenbesitzer nur bei fremdem Eigentum angeben")
        if self.purchase_on and self.warranty_until and self.warranty_until<self.purchase_on:
            raise ValueError("Garantieende liegt vor Kaufdatum")
        return self


class UpdateIn(ItemIn):
    revision: int = Field(ge=0)


class RevisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid",str_strip_whitespace=True)
    revision: int = Field(ge=0)


class MoveIn(RevisionIn):
    place_id: str | None = None
    location_detail: str = Field(default="",max_length=500)
    note: str = Field(default="",max_length=5000)
    occurred_on: date | None = None


class ServiceIn(RevisionIn):
    occurred_on: date
    note: str = Field(min_length=1,max_length=5000)


class ArchiveIn(RevisionIn):
    archived: bool


class LinkIn(RevisionIn):
    loan_id: str


class ItemOut(ItemIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    place_id: str | None
    location_detail: str
    archived: bool
    revision: int
    created_at: datetime
    place_name: str | None = None
    open_loan: LoanOut | None = None


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    kind: str
    occurred_on: date | None
    details: dict
    note: str
    created_at: datetime


def linked_loans(db,owner,item_id,open_only=False,limit=50,offset=0):
    stmt=select(Loan).join(InventoryLoan,InventoryLoan.loan_id==Loan.id).where(
        InventoryLoan.owner_id==owner,InventoryLoan.item_id==item_id,Loan.owner_id==owner)
    if open_only:
        stmt=stmt.where(Loan.returned_at.is_(None))
    return list(db.scalars(stmt.order_by(Loan.lent_at.desc(),Loan.id).limit(limit).offset(offset)))


def outputs(db,owner,rows):
    if not rows:
        return []
    ids=[row.id for row in rows]
    loans={}
    for item_id,loan in db.execute(select(InventoryLoan.item_id,Loan).join(Loan,Loan.id==InventoryLoan.loan_id).where(
        InventoryLoan.owner_id==owner,InventoryLoan.item_id.in_(ids),Loan.owner_id==owner,Loan.returned_at.is_(None)).order_by(Loan.lent_at.desc(),Loan.id)):
        loans.setdefault(item_id,loan)
    places=dict(db.execute(select(Place.id,Place.name).where(Place.owner_id==owner,Place.id.in_([r.place_id for r in rows if r.place_id]))).all())
    people=set(db.scalars(select(Person.id).where(Person.owner_id==owner,Person.id.in_([r.owner_person_id for r in rows if r.owner_person_id]))))
    attachments=set(db.scalars(select(Attachment.id).where(Attachment.owner_id==owner,Attachment.id.in_([r.receipt_attachment_id for r in rows if r.receipt_attachment_id]))))
    result=[]
    for row in rows:
        item=ItemOut.model_validate(row)
        item.place_name=places.get(row.place_id)
        if row.place_id not in places:
            item.place_id=None
        if row.owner_person_id not in people:
            item.owner_person_id=None
        if row.receipt_attachment_id not in attachments:
            item.receipt_attachment_id=None
        if row.id in loans:
            item.open_loan=LoanOut.model_validate(loans[row.id])
        result.append(item.model_dump(mode="json"))
    return result


def due_summary(db,user,limit=20):
    day=today(user)
    horizon=day+timedelta(days=30)
    stmt=select(InventoryItem.id,InventoryItem.name,InventoryItem.next_maintenance_on,InventoryItem.warranty_until).where(
        InventoryItem.owner_id==user.id,InventoryItem.archived.is_(False),
        or_(InventoryItem.next_maintenance_on<=day,InventoryItem.warranty_until.between(day,horizon)))
    rows=db.execute(stmt.order_by(InventoryItem.next_maintenance_on.asc().nullslast(),InventoryItem.warranty_until.asc().nullslast(),InventoryItem.id).limit(limit))
    return [{"id":rid,"name":name,"maintenance_on":service.isoformat() if service and service<=day else None,
             "warranty_until":warranty.isoformat() if warranty and day<=warranty<=horizon else None} for rid,name,service,warranty in rows]


def list_items(db,user,q=None,archived=False,place_id=None,due_only=False,limit=50,offset=0):
    if not 1<=limit<=100 or offset<0 or (q is not None and len(q)>200):
        raise HTTPException(422,"Ungültige Suchparameter")
    stmt=select(InventoryItem).where(InventoryItem.owner_id==user.id,InventoryItem.archived==archived)
    if q and q.strip():
        term=q.strip()
        stmt=stmt.where(or_(*[col.icontains(term,autoescape=True) for col in (InventoryItem.name,InventoryItem.category,InventoryItem.serial_number,InventoryItem.location_detail,InventoryItem.notes)],
            select(Place.id).where(Place.id==InventoryItem.place_id,Place.owner_id==user.id,Place.name.icontains(term,autoescape=True)).exists()))
    if place_id is not None:
        owned(db,Place,user.id,place_id)
        stmt=stmt.where(InventoryItem.place_id==place_id)
    if due_only:
        day=today(user)
        stmt=stmt.where(or_(InventoryItem.next_maintenance_on<=day,InventoryItem.warranty_until.between(day,day+timedelta(days=30))))
    return outputs(db,user.id,list(db.scalars(stmt.order_by(InventoryItem.name,InventoryItem.id).limit(limit).offset(offset))))


def get_item(db,user,item_id):
    return outputs(db,user.id,[owned(db,InventoryItem,user.id,item_id)])[0]


def lock_item(db,user,item_id,revision,allow_archived=False):
    row=db.scalar(select(InventoryItem).where(InventoryItem.id==item_id,InventoryItem.owner_id==user.id).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404,"Gegenstand nicht gefunden")
    if row.revision!=revision:
        raise HTTPException(409,"Gegenstand wurde geändert. Bitte aktualisieren.")
    if row.archived and not allow_archived:
        raise HTTPException(409,"Archivierten Gegenstand zuerst reaktivieren")
    return row


def validate_links(db,user,data):
    if data.owner_person_id is not None:
        person=owned(db,Person,user.id,data.owner_person_id)
        if person.is_self:
            raise HTTPException(422,"Für das eigene Profil bitte eigenes Eigentum wählen")
    if data.receipt_attachment_id is not None:
        attachment=owned(db,Attachment,user.id,data.receipt_attachment_id)
        owned_attachment_resource(db,attachment.resource_type,attachment.resource_id,user)
    if data.purchase_on and data.purchase_on>today(user):
        raise HTTPException(422,"Kaufdatum liegt in der Zukunft")


def create_item(db,user,data,source="web"):
    validate_links(db,user,data)
    return outputs(db,user.id,[persist(db,InventoryItem(owner_id=user.id,**data.model_dump()),"create",source)])[0]


def update_item(db,user,item_id,data,source="web"):
    row=lock_item(db,user,item_id,data.revision)
    validate_links(db,user,data)
    for key,value in data.model_dump(exclude={"revision"}).items():
        setattr(row,key,value)
    row.revision+=1
    return outputs(db,user.id,[persist(db,row,"update",source)])[0]


def record(db,row,kind,occurred_on,details,note,source):
    row.revision+=1
    entry=InventoryHistory(owner_id=row.owner_id,item_id=row.id,kind=kind,occurred_on=occurred_on,details=details,note=note)
    db.add(entry)
    try:
        db.flush()
        db.add_all([AuditEvent(owner_id=row.owner_id,action="update",resource_type="inventory_items",resource_id=row.id,source=source),
                    AuditEvent(owner_id=row.owner_id,action="create",resource_type="inventory_history",resource_id=entry.id,source=source)])
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,"Konkurrierende Änderung. Bitte aktualisieren.") from None
    db.refresh(row)


def move_item(db,user,item_id,data,source="web"):
    row=lock_item(db,user,item_id,data.revision)
    place=owned(db,Place,user.id,data.place_id) if data.place_id is not None else None
    if place and place.archived:
        raise HTTPException(409,"Archivierten Ort zuerst reaktivieren")
    if data.occurred_on and data.occurred_on>today(user):
        raise HTTPException(422,"Standortdatum liegt in der Zukunft")
    previous=db.scalar(select(Place.name).where(Place.id==row.place_id,Place.owner_id==user.id)) if row.place_id else None
    details={"before":{"place_id":row.place_id,"place_name":previous,"location_detail":row.location_detail},
             "after":{"place_id":data.place_id,"place_name":place.name if place else None,"location_detail":data.location_detail}}
    row.place_id=data.place_id
    row.location_detail=data.location_detail
    record(db,row,"location",data.occurred_on,details,data.note,source)
    return outputs(db,user.id,[row])[0]


def service_item(db,user,item_id,data,source="web"):
    row=lock_item(db,user,item_id,data.revision)
    day=today(user)
    if data.occurred_on>day:
        raise HTTPException(422,"Wartungsdatum liegt in der Zukunft")
    previous=db.scalar(select(InventoryHistory.occurred_on).where(InventoryHistory.owner_id==user.id,InventoryHistory.item_id==item_id,InventoryHistory.kind=="maintenance").order_by(InventoryHistory.occurred_on.desc()).limit(1))
    if previous and data.occurred_on<previous:
        raise HTTPException(409,"Wartung liegt vor der letzten dokumentierten Wartung")
    try:
        next_due=data.occurred_on+timedelta(days=row.maintenance_interval_days) if row.maintenance_interval_days else None
    except OverflowError:
        raise HTTPException(422,"Wartungsdatum außerhalb des Kalenders") from None
    old=row.next_maintenance_on
    row.next_maintenance_on=next_due
    record(db,row,"maintenance",data.occurred_on,{"previous_due":old.isoformat() if old else None,"next_due":next_due.isoformat() if next_due else None,"interval_days":row.maintenance_interval_days},data.note,source)
    return outputs(db,user.id,[row])[0]


def archive_item(db,user,item_id,data,source="web"):
    row=lock_item(db,user,item_id,data.revision,True)
    if data.archived and linked_loans(db,user.id,item_id,True,1):
        raise HTTPException(409,"Offene verknüpfte Leihgabe zuerst klären")
    if row.archived!=data.archived:
        row.archived=data.archived
        row.revision+=1
        persist(db,row,"update",source)
    return outputs(db,user.id,[row])[0]


def link_loan(db,user,item_id,data,source="web"):
    row=lock_item(db,user,item_id,data.revision)
    loan=db.scalar(select(Loan).where(Loan.id==data.loan_id,Loan.owner_id==user.id).with_for_update())
    if loan is None:
        raise HTTPException(404,"Leihgabe nicht gefunden")
    existing=db.get(InventoryLoan,loan.id)
    if existing:
        if existing.owner_id==user.id and existing.item_id==item_id:
            return outputs(db,user.id,[row])[0]
        raise HTTPException(409,"Leihgabe ist bereits einem Gegenstand zugeordnet")
    if loan.returned_at is None and linked_loans(db,user.id,item_id,True,1):
        raise HTTPException(409,"Gegenstand hat bereits eine offene verknüpfte Leihgabe")
    db.add(InventoryLoan(loan_id=loan.id,owner_id=user.id,item_id=item_id))
    record(db,row,"loan_link",None,{"loan_id":loan.id,"action":"linked","item_name":loan.item_name},"",source)
    return outputs(db,user.id,[row])[0]


def unlink_loan(db,user,item_id,data,source="web"):
    row=lock_item(db,user,item_id,data.revision,True)
    link=db.scalar(select(InventoryLoan).where(InventoryLoan.loan_id==data.loan_id,InventoryLoan.owner_id==user.id,InventoryLoan.item_id==item_id).with_for_update())
    if link is None:
        raise HTTPException(404,"Verknüpfung nicht gefunden")
    db.delete(link)
    record(db,row,"loan_link",None,{"loan_id":data.loan_id,"action":"unlinked"},"",source)
    return outputs(db,user.id,[row])[0]


def history(db,user,item_id,limit=50,offset=0):
    owned(db,InventoryItem,user.id,item_id)
    if not 1<=limit<=100 or offset<0:
        raise HTTPException(422,"Ungültige Seitengröße")
    stmt=select(InventoryHistory).where(InventoryHistory.owner_id==user.id,InventoryHistory.item_id==item_id)
    return [HistoryOut.model_validate(row).model_dump(mode="json") for row in db.scalars(stmt.order_by(InventoryHistory.created_at.desc(),InventoryHistory.id).limit(limit).offset(offset))]


def loan_history(db,user,item_id,limit=50,offset=0):
    owned(db,InventoryItem,user.id,item_id)
    if not 1<=limit<=100 or offset<0:
        raise HTTPException(422,"Ungültige Seitengröße")
    return [LoanOut.model_validate(row).model_dump(mode="json") for row in linked_loans(db,user.id,item_id,False,limit,offset)]


@router.get("")
def items(q:str|None=Query(None,max_length=200),archived:bool=False,place_id:str|None=None,due_only:bool=False,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),db:Session=Depends(get_db),user:User=Depends(current_user)):
    return list_items(db,user,q,archived,place_id,due_only,limit,offset)


@router.post("",status_code=201)
def create(data:ItemIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return create_item(db,user,data)


@router.get("/{item_id}")
def detail(item_id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return get_item(db,user,item_id)


@router.put("/{item_id}")
def update(item_id:str,data:UpdateIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return update_item(db,user,item_id,data)


@router.post("/{item_id}/move")
def move(item_id:str,data:MoveIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return move_item(db,user,item_id,data)


@router.post("/{item_id}/maintenance")
def maintenance(item_id:str,data:ServiceIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return service_item(db,user,item_id,data)


@router.patch("/{item_id}/archive")
def archive(item_id:str,data:ArchiveIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return archive_item(db,user,item_id,data)


@router.post("/{item_id}/loans/link")
def link(item_id:str,data:LinkIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return link_loan(db,user,item_id,data)


@router.post("/{item_id}/loans/unlink")
def unlink(item_id:str,data:LinkIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return unlink_loan(db,user,item_id,data)


@router.get("/{item_id}/loans")
def loans(item_id:str,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),db:Session=Depends(get_db),user:User=Depends(current_user)):
    return loan_history(db,user,item_id,limit,offset)


@router.get("/{item_id}/history")
def item_history(item_id:str,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),db:Session=Depends(get_db),user:User=Depends(current_user)):
    return history(db,user,item_id,limit,offset)
