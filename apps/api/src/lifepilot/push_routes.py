from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifepilot.db import get_db
from lifepilot.models import AuditEvent, PushSubscription, User
from lifepilot.push_keys import configured_public_key, decode, encode
from lifepilot.security import current_user

router = APIRouter(prefix="/api/push", tags=["Push"])
MAX_DEVICES = 10


def endpoint_allowed(value: str) -> bool:
    try:
        if len(value) > 2048 or any(ord(c) <= 32 or ord(c) >= 127 for c in value) or "\\" in value:
            return False
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        allowed = host in {"fcm.googleapis.com", "android.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"} or host.endswith((".push.services.mozilla.com", ".push.apple.com", ".notify.windows.com"))
        return bool(allowed and parsed.scheme == "https" and parsed.port in (None, 443) and not parsed.username and not parsed.password and not parsed.fragment and parsed.path.startswith("/") and len(parsed.path) > 1)
    except ValueError:
        return False


class PushKeys(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p256dh: str = Field(max_length=120)
    auth: str = Field(max_length=40)

    @field_validator("p256dh")
    @classmethod
    def valid_public(cls, value):
        try:
            raw = decode(value)
            if len(raw) != 65 or raw[0] != 4:
                raise ValueError()
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
            return encode(raw)
        except ValueError:
            raise ValueError("Ungültiger Geräteschlüssel") from None

    @field_validator("auth")
    @classmethod
    def valid_auth(cls, value):
        raw = decode(value)
        if len(raw) != 16:
            raise ValueError("Ungültiger Authentifizierungsschlüssel")
        return encode(raw)


class SubscribeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(max_length=2048)
    keys: PushKeys
    label: str = Field(min_length=1, max_length=120)

    @field_validator("endpoint")
    @classmethod
    def valid_endpoint(cls, value):
        if not endpoint_allowed(value):
            raise ValueError("Nicht unterstützter Push-Dienst")
        return value

    @field_validator("label")
    @classmethod
    def valid_label(cls, value):
        if not value.strip():
            raise ValueError("Gerätename darf nicht leer sein")
        return value.strip()


class DeviceOut(BaseModel):
    id: str
    label: str
    created_at: datetime
    last_sent_at: datetime | None
    active: bool


class PushStatus(BaseModel):
    enabled: bool
    public_key: str | None


def output(row: PushSubscription, user: User, public: str | None):
    return DeviceOut(
        id=row.id, label=row.label, created_at=row.created_at, last_sent_at=row.last_sent_at,
        active=bool(public and row.vapid_public_key == public and row.token_version == user.token_version),
    )


@router.get("/status", response_model=PushStatus)
def status(user: User = Depends(current_user)):
    public = configured_public_key()
    return PushStatus(enabled=bool(public), public_key=public)


@router.get("/devices", response_model=list[DeviceOut])
def devices(db: Session = Depends(get_db), user: User = Depends(current_user)):
    public = configured_public_key()
    return [output(row, user, public) for row in db.scalars(select(PushSubscription).where(PushSubscription.owner_id == user.id).order_by(PushSubscription.created_at.desc()))]


@router.post("/devices", response_model=DeviceOut, status_code=201)
def subscribe(data: SubscribeIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    public = configured_public_key()
    if not public:
        raise HTTPException(503, "Push ist serverseitig nicht konfiguriert")
    owner = db.scalar(select(User).where(User.id == user.id, User.deleted_at.is_(None)).with_for_update().execution_options(populate_existing=True))
    if owner is None:
        raise HTTPException(401, "Konto nicht verfügbar")
    endpoint_hash = sha256(data.endpoint.encode()).hexdigest()
    row = db.scalar(select(PushSubscription).where(PushSubscription.endpoint_hash == endpoint_hash).with_for_update())
    if row is not None and row.owner_id != owner.id:
        raise HTTPException(409, "Dieses Browser-Abonnement ist bereits einem anderen Konto zugeordnet. Bitte im bisherigen Konto entfernen oder ein separates Browserprofil nutzen.")
    now = datetime.now(timezone.utc)
    if row is None:
        count = db.scalar(select(func.count()).select_from(PushSubscription).where(PushSubscription.owner_id == owner.id))
        if count >= MAX_DEVICES:
            raise HTTPException(409, "Maximal zehn Geräte pro Konto")
        row = PushSubscription(owner_id=owner.id, endpoint_hash=endpoint_hash, endpoint=data.endpoint, p256dh=data.keys.p256dh, auth=data.keys.auth, label=data.label, token_version=owner.token_version, vapid_public_key=public, next_check_at=now)
        db.add(row)
    else:
        row.label = data.label
        changed = row.token_version != owner.token_version or row.vapid_public_key != public or row.p256dh != data.keys.p256dh or row.auth != data.keys.auth
        if changed:
            row.p256dh = data.keys.p256dh
            row.auth = data.keys.auth
            row.token_version = owner.token_version
            row.vapid_public_key = public
            row.sent_keys = []
            row.failure_count = 0
            row.next_check_at = now
    try:
        db.flush()
        db.add(AuditEvent(owner_id=owner.id, action="update", resource_type="push_subscriptions", resource_id=row.id, source="rest"))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Gerät bereits registriert. Bitte erneut versuchen.") from None
    return output(row, owner, public)


@router.delete("/devices/{device_id}", status_code=204)
def unsubscribe(device_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(PushSubscription).where(PushSubscription.id == str(device_id), PushSubscription.owner_id == user.id).with_for_update())
    if row is None:
        raise HTTPException(404, "Gerät nicht gefunden")
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="push_subscriptions", resource_id=row.id, source="rest"))
    db.delete(row)
    db.commit()
    return Response(status_code=204)
