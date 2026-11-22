from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.attachment_routes import attachment_files_for_resource, remove_attachment_files
from lifepilot.entity_embedding_jobs import delete_entity_embedding
from lifepilot.models import ApprovalRequest, AuditEvent, Conversation, Event, Gift, Loan, Memory, Person, Project, Relationship, Reminder, Task, User
from lifepilot.schemas import ApprovalOut, AttachmentResourceType
from lifepilot.security import current_user

router = APIRouter(prefix="/api/approvals", tags=["approvals"])
_RESOURCES = {
    "person_delete": Person,
    "relationship_delete": Relationship,
    "memory_delete": Memory,
    "project_delete": Project,
    "conversation_delete": Conversation,
    "task_delete": Task,
    "event_delete": Event,
    "reminder_delete": Reminder,
    "loan_delete": Loan,
    "gift_delete": Gift,
}
_ATTACHMENT_RESOURCES: dict[str, AttachmentResourceType] = {"people": "person", "memories": "memory", "conversations": "conversation", "events": "event", "projects": "project"}


@router.get("", response_model=list[ApprovalOut])
def approval_list(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.scalars(select(ApprovalRequest).where(ApprovalRequest.owner_id == user.id, ApprovalRequest.status == "pending").order_by(ApprovalRequest.created_at)).all()


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
def approval_reject(approval_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    request = _pending_request(db, approval_id, user)
    request.status = "rejected"
    request.decided_at = datetime.now(timezone.utc)
    db.add(AuditEvent(owner_id=user.id, action="reject", resource_type="approval_requests", resource_id=request.id, source="web"))
    db.commit()
    db.refresh(request)
    return request


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
def approval_approve(approval_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    request = _pending_request(db, approval_id, user)
    model = _RESOURCES[request.operation]
    resource = db.scalar(select(model).where(model.id == request.resource_id, model.owner_id == user.id))
    if resource is None:
        raise HTTPException(status_code=404, detail="Zugehöriger Eintrag wurde nicht gefunden")
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


def _pending_request(db: Session, approval_id: str, user: User) -> ApprovalRequest:
    request = db.scalar(select(ApprovalRequest).where(ApprovalRequest.id == approval_id, ApprovalRequest.owner_id == user.id))
    if request is None:
        raise HTTPException(status_code=404, detail="Freigabe nicht gefunden")
    if request.status != "pending":
        raise HTTPException(status_code=409, detail="Freigabe wurde bereits entschieden")
    return request
