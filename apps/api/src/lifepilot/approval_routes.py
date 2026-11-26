from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.approval_policy import active_filters, resource as approval_resource, row_version, now, utc, TTL
from lifepilot.person_merge import plan_merge, apply_merge
from lifepilot.entity_embedding_jobs import enqueue_person_context_embeddings
from lifepilot.attachment_routes import attachment_files_for_resource, remove_attachment_files
from lifepilot.entity_embedding_jobs import delete_entity_embedding
from lifepilot.models import ApprovalRequest, AuditEvent, Conversation, Event, Gift, JournalEntry, Loan, Memory, Person, Pet, Project, Relationship, Reminder, Task, User
from lifepilot.schemas import ApprovalOut, AttachmentResourceType
from lifepilot.security import current_user
from lifepilot.trash_routes import POLICIES, move_to_trash

router = APIRouter(prefix="/api/approvals", tags=["approvals"])
_ATTACHMENT_RESOURCES: dict[str, AttachmentResourceType] = {"people": "person", "memories": "memory", "conversations": "conversation", "events": "event", "projects": "project"}


@router.get("", response_model=list[ApprovalOut])
def approval_list(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.scalars(select(ApprovalRequest).where(*active_filters(user.id)).order_by(ApprovalRequest.created_at)).all()


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
def approval_reject(approval_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    request = _pending_request(db, approval_id, user, lock=True, require_valid=False)
    request.status = "rejected"
    request.decided_at = datetime.now(timezone.utc)
    db.add(AuditEvent(owner_id=user.id, action="reject", resource_type="approval_requests", resource_id=request.id, source="web"))
    db.commit()
    db.refresh(request)
    return request


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
def approval_approve(approval_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    request = _pending_request(db, approval_id, user)
    if request.operation == "person_merge":
        target_id = (request.payload or {}).get("target_id")
        if not isinstance(target_id,str):
            raise HTTPException(409,"Ungültige Zusammenführungsfreigabe")
        plan = plan_merge(db,user.id,request.resource_id,target_id)
        request = _pending_request(db,approval_id,user,lock=True)
        if request.resource_version != plan["version"] or (request.payload or {}).get("target_id") != target_id:
            raise HTTPException(409,"Personen oder Verknüpfungen wurden geändert. Neue Freigabe anfordern.")
        apply_merge(db,user.id,plan)
        request.status = "executed"
        request.decided_at = now()
        db.add(AuditEvent(owner_id=user.id,action="merge",resource_type="people",resource_id=plan["source_id"],source="web"))
        db.commit()
        db.refresh(request)
        enqueue_person_context_embeddings(db,target_id,user.id)
        return request
    resource = approval_resource(db,user.id,request.operation,request.resource_id)
    model = type(resource)
    request = _pending_request(db,approval_id,user,lock=True)
    if request.resource_version != row_version(resource):
        raise HTTPException(409,"Datensatz wurde seit der Anfrage geändert. Neue Freigabe anfordern.")
    if model in POLICIES:
        move_to_trash(db,user.id,model,request.resource_id,approval_id=request.id)
        request.status = "executed"
        request.decided_at = now()
        db.commit()
        db.refresh(request)
        return request
    if request.operation == "relationship_delete":
        delete_entity_embedding(db, "relationship", request.resource_id, user.id)
    if request.operation == "project_delete":
        delete_entity_embedding(db, "project", request.resource_id, user.id)
    if request.operation == "conversation_delete":
        delete_entity_embedding(db, "conversation", request.resource_id, user.id)
    if request.operation == "task_delete":
        delete_entity_embedding(db, "task", request.resource_id, user.id)
    attachment_resource = _ATTACHMENT_RESOURCES.get(model.__tablename__)
    attachment_paths = attachment_files_for_resource(db, user.id, attachment_resource, resource.id) if attachment_resource is not None else []
    db.delete(resource)
    request.status = "executed"
    request.decided_at = datetime.now(timezone.utc)
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type=model.__tablename__, resource_id=request.resource_id, source="web"))
    db.commit()
    remove_attachment_files(attachment_paths)
    db.refresh(request)
    return request


def _pending_request(db: Session, approval_id: str, user: User, lock: bool = False, require_valid: bool = True) -> ApprovalRequest:
    stmt=select(ApprovalRequest).where(ApprovalRequest.id == approval_id, ApprovalRequest.owner_id == user.id)
    if lock:
        stmt=stmt.with_for_update().execution_options(populate_existing=True)
    request=db.scalar(stmt)
    if request is None:
        raise HTTPException(status_code=404, detail="Freigabe nicht gefunden")
    if request.status != "pending":
        raise HTTPException(status_code=409, detail="Freigabe wurde bereits entschieden")
    if require_valid and (request.resource_version is None or utc(request.created_at)+TTL<=now()):
        raise HTTPException(409,"Freigabe ist abgelaufen oder stammt aus einer älteren Version. Neue Freigabe anfordern.")
    return request
