"""Explicitly scoped, transactional recycle bin for records without file payloads."""
import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Date, DateTime, and_, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import get_db
from lifepilot.models import (
    ApprovalRequest, AuditEvent, EntityEmbedding, FocusSession, Gift, InventoryItem, InventoryLoan,
    JournalEntry, JournalEntryEvent, JournalEntryPerson, JournalEntryProject, Loan, Place, PlaceEntry,
    Reminder, Task, TaskStep, TrashEntry, User, WorkCheckpoint,
)
from lifepilot.security import current_user, verify_password

router = APIRouter(prefix="/api/trash", tags=["Papierkorb"])
MAX_ROWS = 1000
MAX_BYTES = 2 * 1024 * 1024
# Explicit dependency policies: restore cascaded children, reconnect detached
# references only if still empty. Derived embeddings are rebuilt, not copied.
POLICIES = {
    Task: ([(TaskStep,"task_id"),(Reminder,"task_id")],[(FocusSession,"task_id"),(WorkCheckpoint,"task_id")],[(EntityEmbedding,"task_id")]),
    JournalEntry: ([(JournalEntryPerson,"entry_id"),(JournalEntryProject,"entry_id"),(JournalEntryEvent,"entry_id")],[],[]),
    Loan: ([(InventoryLoan,"loan_id")],[],[]),
    Gift: ([],[],[]),
    Place: ([(PlaceEntry,"place_id")],[(InventoryItem,"place_id")],[]),
    PlaceEntry: ([],[],[]),
}
ROOTS = {model.__tablename__:model for model in POLICIES}
TABLES = {model.__tablename__:model.__table__ for model in {*POLICIES,*(m for policy in POLICIES.values() for group in policy for m,_ in group)}}
APPROVALS = {"tasks":"task_delete","journal_entries":"journal_delete","loans":"loan_delete","gifts":"gift_delete"}


def now():
    return datetime.now(timezone.utc)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def encode(row):
    return {key:value.isoformat() if isinstance(value,(datetime,date)) else value for key,value in row.items()}


def decode(table, data):
    if set(data)!=set(table.c.keys()):
        raise HTTPException(409,"Papierkorb-Datensatz passt nicht zum aktuellen Schema")
    return {key:(datetime.fromisoformat(value) if value is not None and isinstance(table.c[key].type,DateTime)
                 else date.fromisoformat(value) if value is not None and isinstance(table.c[key].type,Date)
                 else value) for key,value in data.items()}


def pk_filter(table,data):
    return and_(*(column==data[column.name] for column in table.primary_key.columns))


def cleanup_expired(db,owner=None):
    stmt=select(TrashEntry.id).where(TrashEntry.expires_at<=now())
    if owner is not None:
        stmt=stmt.where(TrashEntry.owner_id==owner)
    else:
        stmt=stmt.order_by(TrashEntry.expires_at,TrashEntry.id).limit(500)
    db.execute(delete(TrashEntry).where(TrashEntry.id.in_(stmt),TrashEntry.expires_at<=now()))


def related(db,model,column,rid,owner,remaining):
    table=model.__table__
    # Never cascade into an inconsistent cross-account reference.
    if db.scalar(select(table.c.owner_id).where(table.c[column]==rid,table.c.owner_id!=owner).limit(1)) is not None:
        raise HTTPException(409,"Kontofremde Verknüpfung verhindert die sichere Löschung")
    rows=list(db.execute(select(table).where(table.c[column]==rid,table.c.owner_id==owner).limit(remaining+1).with_for_update()).mappings())
    if len(rows)>remaining:
        raise HTTPException(409,"Zu viele abhängige Datensätze für eine sichere Wiederherstellung")
    return rows


def move_to_trash(db,owner,model,rid,source="web",approval_id=None):
    """Does not commit. Caller commits deletion, snapshot and approval together."""
    if model not in POLICIES:
        raise HTTPException(422,"Dieser Datensatztyp unterstützt noch keinen Papierkorb")
    table=model.__table__
    root=db.execute(select(table).where(table.c.id==rid,table.c.owner_id==owner).with_for_update()).mappings().first()
    if root is None:
        raise HTTPException(404,"Eintrag nicht gefunden")
    cleanup_expired(db,owner)
    children,detached,derived=POLICIES[model]
    snapshots=[{"table":table.name,"data":encode(root)}]
    reconnect=[]
    remaining=MAX_ROWS-1
    for child,column in children:
        rows=related(db,child,column,rid,owner,remaining)
        remaining-=len(rows)
        snapshots.extend({"table":child.__tablename__,"data":encode(row)} for row in rows)
    for child,column in detached:
        rows=related(db,child,column,rid,owner,remaining)
        remaining-=len(rows)
        for row in rows:
            keys={c.name:row[c.name] for c in child.__table__.primary_key.columns}
            # Revisions for inventory guard against stale edits between detach and restore.
            reconnect.append({"table":child.__tablename__,"keys":keys,"column":column,"revision":row.get("revision")})
    for child,column in derived:
        related(db,child,column,rid,owner,MAX_ROWS)
    snapshot={"version":1,"rows":snapshots,"reconnect":reconnect}
    if len(json.dumps(snapshot,ensure_ascii=False).encode())>MAX_BYTES:
        raise HTTPException(409,"Papierkorb-Sicherung ist zu groß; nichts wurde gelöscht")
    created=now()
    entry=TrashEntry(owner_id=owner,resource_type=table.name,resource_id=rid,
                     label=(root.get("title") or root.get("name") or root.get("item_name") or "Ohne Titel")[:240],
                     snapshot=snapshot,deleted_at=created,expires_at=created+timedelta(days=settings.trash_retention_days))
    db.add(entry)
    for child,column in children+derived:
        t=child.__table__
        db.execute(delete(t).where(t.c[column]==rid,t.c.owner_id==owner))
    for child,column in detached:
        t=child.__table__
        values={column:None}
        if "revision" in t.c:
            values["revision"]=t.c.revision+1
        db.execute(update(t).where(t.c[column]==rid,t.c.owner_id==owner).values(**values))
    db.execute(delete(table).where(table.c.id==rid,table.c.owner_id==owner))
    if table.name in APPROVALS:
        stmt=update(ApprovalRequest).where(ApprovalRequest.owner_id==owner,ApprovalRequest.operation==APPROVALS[table.name],
            ApprovalRequest.resource_id==rid,ApprovalRequest.status=="pending")
        if approval_id:
            stmt=stmt.where(ApprovalRequest.id!=approval_id)
        db.execute(stmt.values(status="rejected",decided_at=created))
    db.add(AuditEvent(owner_id=owner,action="delete",resource_type=table.name,resource_id=rid,source=source))
    db.flush()
    return entry


def trash_metadata(row):
    return {"id":row.id,"resource_type":row.resource_type,"resource_id":row.resource_id,"label":row.label,
            "deleted_at":utc(row.deleted_at).isoformat(),"expires_at":utc(row.expires_at).isoformat(),
            "related_records":len(row.snapshot["rows"])-1+len(row.snapshot["reconnect"])}


def list_trash(db,owner,limit=50,offset=0):
    if not 1<=limit<=100 or offset<0:
        raise HTTPException(422,"Ungültige Seitengröße")
    return [trash_metadata(row) for row in db.scalars(select(TrashEntry).where(TrashEntry.owner_id==owner,TrashEntry.expires_at>now())
        .order_by(TrashEntry.deleted_at.desc(),TrashEntry.id).limit(limit).offset(offset))]


def lock_entry(db,owner,entry_id):
    row=db.scalar(select(TrashEntry).where(TrashEntry.id==entry_id,TrashEntry.owner_id==owner).with_for_update().execution_options(populate_existing=True))
    if row is None or utc(row.expires_at)<=now():
        raise HTTPException(404,"Papierkorbeintrag fehlt oder ist abgelaufen")
    return row


def validate_references(db,table,data,owner):
    if data.get("owner_id")!=owner:
        raise HTTPException(409,"Ungültige Kontozuordnung in der Sicherung")
    for fk in table.foreign_keys:
        value=data[fk.parent.name]
        if value is None:
            continue
        target=fk.column.table
        if target.name=="users":
            if value!=owner:
                raise HTTPException(409,"Ungültige Kontozuordnung")
            continue
        if "owner_id" not in target.c:
            raise HTTPException(409,"Nicht unterstützte Verknüpfung")
        if db.scalar(select(fk.column).where(fk.column==value,target.c.owner_id==owner).with_for_update()) is None:
            raise HTTPException(409,"Eine verknüpfte Ressource fehlt. Bitte zuerst diese Ressource wiederherstellen.")


def restore(db,owner,entry_id,source="web"):
    row=lock_entry(db,owner,entry_id)
    model=ROOTS.get(row.resource_type)
    snapshot=row.snapshot
    if model is None or snapshot.get("version")!=1:
        raise HTTPException(409,"Nicht unterstützte Sicherungsversion")
    children,detached,_=POLICIES[model]
    allowed={row.resource_type,*[m.__tablename__ for m,_ in children]}
    allowed_reconnect={(m.__tablename__,column) for m,column in detached}
    try:
        for part in snapshot["rows"]:
            if part["table"] not in allowed:
                raise HTTPException(409,"Nicht unterstützte Sicherung")
            table=TABLES[part["table"]]
            data=decode(table,part["data"])
            validate_references(db,table,data,owner)
            if db.execute(select(table).where(pk_filter(table,data)).limit(1)).first() is not None:
                raise HTTPException(409,"Eine ursprüngliche ID ist bereits belegt")
            # One open linked loan per item, even across a trash/restore cycle.
            if table.name=="inventory_loans":
                item=InventoryItem.__table__
                db.execute(select(item.c.id).where(item.c.id==data["item_id"],item.c.owner_id==owner).with_for_update()).first()
                loan=Loan.__table__
                open_loan=db.scalar(select(loan.c.id).where(loan.c.id==data["loan_id"],loan.c.returned_at.is_(None)))
                link=InventoryLoan.__table__
                if open_loan and db.scalar(select(link.c.loan_id).join(loan,loan.c.id==link.c.loan_id).where(
                    link.c.item_id==data["item_id"],link.c.owner_id==owner,loan.c.owner_id==owner,loan.c.returned_at.is_(None)).limit(1)):
                    raise HTTPException(409,"Gegenstand hat bereits eine andere offene Leihgabe")
                if open_loan and db.scalar(select(item.c.archived).where(item.c.id==data["item_id"])):
                    raise HTTPException(409,"Gegenstand zuerst reaktivieren")
            db.execute(table.insert().values(**data))
        for part in snapshot["reconnect"]:
            if (part["table"],part["column"]) not in allowed_reconnect:
                raise HTTPException(409,"Nicht unterstützte Verknüpfung")
            table=TABLES[part["table"]]
            column=part["column"]
            condition=and_(pk_filter(table,part["keys"]),table.c.owner_id==owner,table.c[column].is_(None))
            values={column:row.resource_id}
            if "revision" in table.c:
                condition=and_(condition,table.c.revision==part["revision"]+1)
                values["revision"]=table.c.revision+1
            result=db.execute(update(table).where(condition).values(**values))
            if result.rowcount!=1:
                raise HTTPException(409,"Eine frühere Verknüpfung wurde inzwischen geändert oder gelöscht. Nichts wurde wiederhergestellt.")
        resource_type,resource_id=row.resource_type,row.resource_id
        db.add(AuditEvent(owner_id=owner,action="restore",resource_type=resource_type,resource_id=resource_id,source=source))
        db.delete(row)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,"Wiederherstellung kollidiert mit vorhandenen Daten. Nichts wurde verändert.") from None
    if resource_type=="tasks":
        from lifepilot.entity_embedding_jobs import enqueue_entity_embedding
        enqueue_entity_embedding("task",resource_id,owner)
    return {"resource_type":resource_type,"resource_id":resource_id}


class PurgeIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    password:str=Field(min_length=1,max_length=1024)


@router.get("")
def get_trash(limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),db:Session=Depends(get_db),user:User=Depends(current_user)):
    return {"retention_days":settings.trash_retention_days,"items":list_trash(db,user.id,limit,offset)}


@router.post("/{entry_id}/restore")
def restore_entry(entry_id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return restore(db,user.id,entry_id)


@router.post("/{entry_id}/purge",status_code=204)
def purge_entry(entry_id:str,data:PurgeIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    if not verify_password(data.password,user.password_hash):
        raise HTTPException(403,"Passwort ist nicht korrekt")
    row=lock_entry(db,user.id,entry_id)
    db.add(AuditEvent(owner_id=user.id,action="purge",resource_type=row.resource_type,resource_id=row.resource_id,source="web"))
    db.delete(row)
    db.commit()
