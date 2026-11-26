"""Server-issued, time-limited approvals bound to the exact requested operation."""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json

from fastapi import HTTPException
from sqlalchemy import func, select, update

from lifepilot.models import (ApprovalRequest, Conversation, Event, Gift, JournalEntry, Loan, Memory,
    Person, PersonContactMethod, Pet, Project, Relationship, Reminder, Task, User)

DELETE_MODELS = {
    "person_delete":Person,"relationship_delete":Relationship,"memory_delete":Memory,
    "project_delete":Project,"conversation_delete":Conversation,"task_delete":Task,
    "event_delete":Event,"reminder_delete":Reminder,"loan_delete":Loan,"gift_delete":Gift,
    "journal_delete":JournalEntry,"pet_delete":Pet,"person_contact_method_delete":PersonContactMethod,
}
TTL = timedelta(hours=24)
MAX_PENDING = 100


def now():
    return datetime.now(timezone.utc)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def serial(value):
    if isinstance(value,datetime):
        return utc(value).isoformat()
    if isinstance(value,date):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def fingerprint(value):
    return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":"),default=serial).encode()).hexdigest()


def active_filters(owner):
    return (ApprovalRequest.owner_id==owner,ApprovalRequest.status=="pending",
            ApprovalRequest.created_at>now()-TTL,ApprovalRequest.resource_version.is_not(None))


def resource(db,owner,operation,rid):
    model=DELETE_MODELS.get(operation)
    if model is None:
        raise HTTPException(422,"Nicht unterstützte Freigabe")
    row=db.scalar(select(model).where(model.id==rid,model.owner_id==owner).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404,"Eintrag nicht gefunden")
    if isinstance(row,Person) and row.is_self:
        raise HTTPException(409,"Das eigene Personenprofil kann nicht gelöscht werden")
    return row


def row_version(row):
    return fingerprint({c.name:getattr(row,c.name) for c in row.__table__.columns})


def result(row):
    return {"approval_id":row.id,"operation":row.operation,"resource_id":row.resource_id,"status":row.status,
            "expires_at":(utc(row.created_at)+TTL).isoformat(),
            "message":"Im LifePilot-Eingang durch den Benutzer freigeben. Noch nicht ausgeführt."}


def queue(db,owner,operation,rid,label,payload=None):
    # Serialize per-account queue writers, then lock the affected record(s).
    if db.scalar(select(User.id).where(User.id==owner,User.deleted_at.is_(None)).with_for_update()) is None:
        raise HTTPException(401,"Ungültige Anmeldung")
    payload=payload or {}
    if operation=="person_merge":
        from lifepilot.person_merge import plan_merge
        plan=plan_merge(db,owner,rid,payload["target_id"])
        version=plan["version"]
        label=plan["label"]
        payload={"target_id":plan["target_id"],"source_name":plan["source_name"],"target_name":plan["target_name"],"linked_records":len(plan["links"])}
    else:
        row=resource(db,owner,operation,rid)
        version=row_version(row)
        if isinstance(row,Person):
            label=f"{row.first_name} {row.last_name}".strip()
        elif isinstance(row,PersonContactMethod):
            label=f"{row.method_type}: {row.label} {row.value}"
        elif isinstance(row,Relationship):
            names={p.id:f"{p.first_name} {p.last_name}".strip() for p in db.scalars(select(Person).where(Person.owner_id==owner,Person.id.in_([row.source_person_id,row.target_person_id])))}
            label=f"{names.get(row.source_person_id,'Person')[:80]} · {row.relationship_type[:65]} · {names.get(row.target_person_id,'Person')[:80]}"
        else:
            label=getattr(row,"title",getattr(row,"name",getattr(row,"item_name",label)))
    cutoff=now()-TTL
    db.execute(update(ApprovalRequest).where(ApprovalRequest.owner_id==owner,ApprovalRequest.status=="pending",
        ApprovalRequest.created_at<=cutoff).values(status="expired",decided_at=now()))
    old=db.scalars(select(ApprovalRequest).where(*active_filters(owner),ApprovalRequest.operation==operation,
        ApprovalRequest.resource_id==rid).order_by(ApprovalRequest.created_at,ApprovalRequest.id).with_for_update().execution_options(populate_existing=True)).all()
    for entry in old:
        if entry.resource_version==version and (entry.payload or {})==payload:
            db.commit()
            return result(entry)
    # Supersede only after a different version/target is deliberately requested.
    for entry in old:
        entry.status="rejected"
        entry.decided_at=now()
    db.flush()
    if db.scalar(select(func.count()).select_from(ApprovalRequest).where(*active_filters(owner)))>=MAX_PENDING:
        raise HTTPException(409,"Zu viele offene Freigaben. Bitte zuerst im Eingang bearbeiten.")
    entry=ApprovalRequest(owner_id=owner,operation=operation,resource_id=rid,resource_label=label[:240],
                          resource_version=version,payload=payload,created_at=now())
    db.add(entry);db.commit();db.refresh(entry)
    return result(entry)
