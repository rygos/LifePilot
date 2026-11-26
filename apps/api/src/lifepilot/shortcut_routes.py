from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lifepilot.capture_routes import capture_create
from lifepilot.capture_schemas import CaptureIn
from lifepilot.db import get_db
from lifepilot.models import AuditEvent, CaptureKey, User
from lifepilot.security import current_user, verify_password

router = APIRouter(prefix="/api/shortcuts", tags=["Kurzbefehle"])
bearer = HTTPBearer(auto_error=False)
PREFIX = "lp_capture_"
MAX_ACTIVE_KEYS = 20
REQUESTS_PER_HOUR = 60


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def digest(secret: str) -> str:
    return sha256(secret.encode("utf-8")).hexdigest()


class KeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=120)
    expires_in_days: int = Field(default=90, ge=1, le=365)
    current_password: str = Field(min_length=1, max_length=1024)

    @field_validator("label")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Bezeichnung darf nicht leer sein")
        return value.strip()


class KeyOut(BaseModel):
    id: str
    label: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    active: bool


class KeyCreated(KeyOut):
    token: str


class ShortcutCaptureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original_text: str = Field(min_length=1, max_length=20000)
    client_request_id: UUID | None = None
    captured_at: AwareDatetime | None = None

    @field_validator("original_text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Erfassung darf nicht leer sein")
        return value.strip()

    @field_validator("captured_at")
    @classmethod
    def valid_date(cls, value):
        if value is not None and value > datetime.now(timezone.utc) + timedelta(minutes=10):
            raise ValueError("Erfassungszeit darf nicht in der Zukunft liegen")
        return value


class ShortcutReceipt(BaseModel):
    id: str
    status: Literal["saved"] = "saved"


def key_output(row: CaptureKey, user: User, now: datetime) -> KeyOut:
    return KeyOut(
        id=row.id, label=row.label, created_at=utc(row.created_at), expires_at=utc(row.expires_at),
        revoked_at=utc(row.revoked_at) if row.revoked_at else None,
        last_used_at=utc(row.last_used_at) if row.last_used_at else None,
        active=row.revoked_at is None and utc(row.expires_at) > now and row.token_version == user.token_version,
    )


@router.get("/keys", response_model=list[KeyOut])
def list_keys(response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(timezone.utc)
    rows = list(db.scalars(select(CaptureKey).where(CaptureKey.owner_id == user.id).order_by(CaptureKey.created_at.desc())))
    output = [key_output(row, user, now) for row in rows]
    return [row for row in output if row.active] + [row for row in output if not row.active][:100]


@router.post("/keys", response_model=KeyCreated, status_code=201)
def create_key(data: KeyCreate, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    # Serialize key creation and use the current account password/version.
    owner = db.scalar(select(User).where(User.id == user.id, User.deleted_at.is_(None)).with_for_update().execution_options(populate_existing=True))
    if owner is None or not verify_password(data.current_password, owner.password_hash):
        raise HTTPException(403, "Das aktuelle Passwort ist falsch")
    now = datetime.now(timezone.utc)
    count = db.scalar(select(func.count()).select_from(CaptureKey).where(
        CaptureKey.owner_id == owner.id, CaptureKey.revoked_at.is_(None),
        CaptureKey.expires_at > now, CaptureKey.token_version == owner.token_version,
    ))
    if count >= MAX_ACTIVE_KEYS:
        raise HTTPException(409, "Maximal 20 aktive Erfassungsschlüssel pro Konto")
    secret = PREFIX + token_urlsafe(32)
    row = CaptureKey(owner_id=owner.id, label=data.label, secret_hash=digest(secret), token_version=owner.token_version, expires_at=now + timedelta(days=data.expires_in_days))
    db.add(row)
    db.flush()
    db.add(AuditEvent(owner_id=owner.id, action="create", resource_type="capture_keys", resource_id=row.id, source="rest"))
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return KeyCreated(**key_output(row, owner, now).model_dump(), token=secret)


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(key_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(CaptureKey).where(CaptureKey.id == str(key_id), CaptureKey.owner_id == user.id).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, "Erfassungsschlüssel nicht gefunden")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.add(AuditEvent(owner_id=user.id, action="update", resource_type="capture_keys", resource_id=row.id, source="rest"))
        db.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


def invalid_key():
    return HTTPException(401, "Ungültiger oder abgelaufener Erfassungsschlüssel", headers={"WWW-Authenticate": "Bearer"})


@router.post("/capture", response_model=ShortcutReceipt, status_code=201)
def shortcut_capture(data: ShortcutCaptureIn, response: Response, credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)):
    # Opaque keys are deliberately not accepted by the JWT or MCP authentication.
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise invalid_key()
    secret = credentials.credentials
    if not secret.startswith(PREFIX) or len(secret) != len(PREFIX) + 43:
        raise invalid_key()
    row = db.scalar(select(CaptureKey).where(CaptureKey.secret_hash == digest(secret)).with_for_update().execution_options(populate_existing=True))
    now = datetime.now(timezone.utc)
    if row is None or row.revoked_at is not None or utc(row.expires_at) <= now:
        raise invalid_key()
    owner = db.scalar(select(User).where(User.id == row.owner_id, User.deleted_at.is_(None)).execution_options(populate_existing=True))
    if owner is None or owner.token_version != row.token_version:
        raise invalid_key()
    if row.window_started_at is None or utc(row.window_started_at) + timedelta(hours=1) <= now:
        row.window_started_at = now
        row.window_count = 0
    if row.window_count >= REQUESTS_PER_HOUR:
        retry = max(1, int((utc(row.window_started_at) + timedelta(hours=1) - now).total_seconds()) + 1)
        raise HTTPException(429, "Zu viele Erfassungen mit diesem Schlüssel", headers={"Retry-After": str(retry)})
    row.window_count += 1
    row.last_used_at = now
    # Persist the quota before the capture service, which manages its own commits.
    db.commit()
    captured = capture_create(CaptureIn(original_text=data.original_text, client_request_id=data.client_request_id, captured_at=data.captured_at, source="capture"), db, owner)
    response.headers["Cache-Control"] = "no-store"
    return ShortcutReceipt(id=captured.id)
