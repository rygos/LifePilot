from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, UOWTransaction

from lifepilot.db import Base
from lifepilot.models import AuditEvent

ACTOR_KEY = "lifepilot_audit_actor_id"
CHANGES_KEY = "lifepilot_audit_changes"


class AuditEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    action: str
    resource_type: str
    resource_id: str
    source: str
    created_at: datetime


@event.listens_for(Session, "before_flush")
def collect_changes(session: Session, flush_context: UOWTransaction, instances: Sequence[Base] | None) -> None:
    actor_id = session.info.get(ACTOR_KEY)
    if not isinstance(actor_id, str):
        return
    changes: list[tuple[Base, str]] = []
    changes.extend((row, "create") for row in session.new if not isinstance(row, AuditEvent))
    changes.extend((row, "update") for row in session.dirty if not isinstance(row, AuditEvent) and session.is_modified(row, include_collections=False))
    changes.extend((row, "delete") for row in session.deleted if not isinstance(row, AuditEvent))
    session.info[CHANGES_KEY] = changes


@event.listens_for(Session, "after_flush_postexec")
def write_changes(session: Session, flush_context: UOWTransaction) -> None:
    actor_id = session.info.get(ACTOR_KEY)
    changes = session.info.pop(CHANGES_KEY, [])
    if not isinstance(actor_id, str):
        return
    for entity, action in changes:
        identity = inspect(entity).identity
        if identity is None:
            raise RuntimeError("Audit-Ereignis kann ohne Ressourcen-ID nicht gespeichert werden")
        resource_id = ":".join(str(part) for part in identity)
        session.add(AuditEvent(owner_id=actor_id, action=action, resource_type=entity.__tablename__, resource_id=resource_id, source="mcp"))
