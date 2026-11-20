import logging
from datetime import datetime
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import get_db
from lifepilot.models import AuditEvent, User
from lifepilot.security import current_user

router = APIRouter(prefix="/api/admin", tags=["Administration"])
logger = logging.getLogger(__name__)


def call_portainer_webhook(webhook_url: str) -> int:
    request = Request(webhook_url, data=b"", method="POST")
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=15) as response:
            if response.geturl() != webhook_url:
                return 502
            return response.status
    except HTTPError as exc:
        return exc.code
    except (URLError, TimeoutError, OSError, ValueError):
        raise


class AdminUserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    full_name: str
    role: Literal["user", "admin"]
    created_at: datetime


class UserRoleUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["user", "admin"]


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administratorrechte erforderlich")
    return user


@router.get("/users", response_model=list[AdminUserView])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[AdminUserView]:
    users = db.scalars(select(User).order_by(User.username)).all()
    return [AdminUserView.model_validate(user) for user in users]


@router.patch("/users/{user_id}/role", response_model=AdminUserView)
def update_user_role(
    user_id: str,
    data: UserRoleUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
) -> AdminUserView:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    if target.role == data.role:
        return AdminUserView.model_validate(target)
    if target.role == "admin" and data.role == "user":
        admin_count = db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) or 0
        if admin_count <= 1:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Mindestens ein Administrator muss bestehen bleiben")
    target.role = data.role
    db.add(AuditEvent(owner_id=actor.id, action="update", resource_type="user_role", resource_id=target.id, source="web"))
    db.commit()
    db.refresh(target)
    return AdminUserView.model_validate(target)


@router.get("/app-update")
def app_update_status(_: User = Depends(require_admin)) -> dict[str, bool | str]:
    return {"configured": bool(settings.portainer_webhook_url.strip()), "source": "main"}


@router.post("/app-update", status_code=status.HTTP_202_ACCEPTED)
def request_app_update(db: Session = Depends(get_db), actor: User = Depends(require_admin)) -> dict[str, str]:
    webhook_url = settings.portainer_webhook_url.strip()
    if not webhook_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Der Portainer-Git-Webhook ist nicht konfiguriert")
    if not webhook_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Die Portainer-Webhook-Adresse ist ungültig")
    try:
        response_status = call_portainer_webhook(webhook_url)
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("Portainer-Webhook konnte nicht erreicht werden (%s)", type(exc).__name__)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Portainer konnte nicht erreicht werden") from None
    if not 200 <= response_status < 300:
        logger.warning("Portainer-Webhook antwortete mit HTTP %s", response_status)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Portainer hat die Aktualisierung nicht angenommen")
    db.add(AuditEvent(owner_id=actor.id, action="update", resource_type="application_update", resource_id="main", source="web"))
    db.commit()
    return {"status": "triggered", "message": "Portainer hat die Git-Aktualisierung gestartet. Die Datenbankmigrationen laufen beim App-Start."}
