from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.models import AuditEvent, DavKey, User
from lifepilot.security import current_user, verify_password
from lifepilot.shortcut_routes import KeyCreate, utc

router = APIRouter(prefix="/api/dav", tags=["Kalenderzugang"])
basic = HTTPBasic(auto_error=False, realm="LifePilot DAV")
PREFIX = "lp_dav_"
SCOPE = "calendar:read"


class DavKeyCreate(KeyCreate):
    scope: Literal["calendar:read", "contacts:read"] = SCOPE


class DavKeyOut(BaseModel):
    id: str
    label: str
    scope: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    active: bool


class DavKeyCreated(DavKeyOut):
    username: str
    password: str
    calendar_path: str | None = None
    addressbook_path: str | None = None


def output(row, user, now):
    return DavKeyOut(id=row.id, label=row.label, scope=row.scope, created_at=utc(row.created_at),
                     expires_at=utc(row.expires_at), revoked_at=utc(row.revoked_at) if row.revoked_at else None,
                     active=row.revoked_at is None and utc(row.expires_at) > now and row.token_version == user.token_version)


@router.get("/keys", response_model=list[DavKeyOut])
def list_keys(response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(timezone.utc)
    rows = list(db.scalars(select(DavKey).where(DavKey.owner_id == user.id).order_by(DavKey.created_at.desc())))
    result = [output(row, user, now) for row in rows]
    return [r for r in result if r.active] + [r for r in result if not r.active][:100]


@router.post("/keys", response_model=DavKeyCreated, status_code=201)
def create_key(data: DavKeyCreate, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owner = db.scalar(select(User).where(User.id == user.id, User.deleted_at.is_(None)).with_for_update().execution_options(populate_existing=True))
    if owner is None or not verify_password(data.current_password, owner.password_hash):
        raise HTTPException(403, "Das aktuelle Passwort ist falsch")
    now = datetime.now(timezone.utc)
    count = db.scalar(select(func.count()).select_from(DavKey).where(DavKey.owner_id == owner.id, DavKey.revoked_at.is_(None), DavKey.expires_at > now, DavKey.token_version == owner.token_version))
    if count >= 20:
        raise HTTPException(409, "Maximal 20 aktive DAV-Zugänge")
    secret = PREFIX + token_urlsafe(32)
    row = DavKey(owner_id=owner.id, label=data.label, scope=data.scope, secret_hash=sha256(secret.encode()).hexdigest(), token_version=owner.token_version, expires_at=now + timedelta(days=data.expires_in_days))
    db.add(row)
    db.flush()
    db.add(AuditEvent(owner_id=owner.id, action="create", resource_type="dav_keys", resource_id=row.id, source="rest"))
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return DavKeyCreated(**output(row, owner, now).model_dump(), username=owner.id, password=secret, calendar_path=f"/dav/calendars/{owner.id}/lifepilot/" if row.scope == SCOPE else None, addressbook_path=f"/carddav/addressbooks/{owner.id}/lifepilot/" if row.scope == "contacts:read" else None)


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(key_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(DavKey).where(DavKey.id == str(key_id), DavKey.owner_id == user.id).with_for_update())
    if row is None:
        raise HTTPException(404, "DAV-Zugang nicht gefunden")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.add(AuditEvent(owner_id=user.id, action="update", resource_type="dav_keys", resource_id=row.id, source="rest"))
        db.commit()
    return Response(status_code=204)


def unauthorized():
    return HTTPException(401, "Ungültiger DAV-Zugang", headers={"WWW-Authenticate": 'Basic realm="LifePilot DAV"', "Cache-Control": "no-store"})


def authenticate_dav(credentials: HTTPBasicCredentials | None, db: Session, scope: str) -> User:
    if credentials is None or not credentials.password.startswith(PREFIX) or len(credentials.password) != len(PREFIX) + 43:
        raise unauthorized()
    row = db.scalar(select(DavKey).where(DavKey.secret_hash == sha256(credentials.password.encode()).hexdigest(), DavKey.owner_id == credentials.username, DavKey.scope == scope))
    if row is None or row.revoked_at is not None or utc(row.expires_at) <= datetime.now(timezone.utc):
        raise unauthorized()
    owner = db.scalar(select(User).where(User.id == row.owner_id, User.deleted_at.is_(None)))
    if owner is None or owner.token_version != row.token_version:
        raise unauthorized()
    return owner


def dav_user(credentials: HTTPBasicCredentials | None = Depends(basic), db: Session = Depends(get_db)) -> User:
    return authenticate_dav(credentials, db, SCOPE)


def carddav_user(credentials: HTTPBasicCredentials | None = Depends(basic), db: Session = Depends(get_db)) -> User:
    return authenticate_dav(credentials, db, "contacts:read")
