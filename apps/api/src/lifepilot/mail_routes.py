"""Explicit, read-only import from an administrator-configured IMAPS server."""
import hashlib
import imaplib
import re
import ssl
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from threading import BoundedSemaphore
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from lifepilot.capture_routes import capture_create
from lifepilot.capture_schemas import CaptureIn
from lifepilot.config import settings
from lifepilot.db import get_db
from lifepilot.models import Capture, Person, PersonContactMethod, User
from lifepilot.security import current_user

class MailRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                # Never echo credentials in validation responses.
                return JSONResponse({"detail": "Ungültige E-Mail-Anfrage"}, status_code=422, headers={"Cache-Control":"no-store"})
        return safe_handler


router = APIRouter(prefix="/api/mail", tags=["E-Mail"], route_class=MailRoute)
MAX_MESSAGE = 256 * 1024
MAX_TEXT = 16000
slots = BoundedSemaphore(2)


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=320, pattern=r"^[A-Za-z0-9._+@%\-]+$")
    password: SecretStr = Field(min_length=1, max_length=1024)

    @field_validator("password")
    @classmethod
    def valid_password(cls, value):
        if any(c in value.get_secret_value() for c in ("\r", "\n", "\x00")):
            raise ValueError("Ungültiges Passwortformat")
        return value


class MessageRequest(Credentials):
    uid: int = Field(ge=1, le=4294967295)
    uidvalidity: int = Field(ge=1, le=4294967295)


class ImportRequest(MessageRequest):
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def one_line(value, limit=1000):
    return " ".join(str(value or "").split())[:limit]


def ok(result):
    status, values = result
    if status != "OK":
        raise HTTPException(502, "IMAP-Abfrage fehlgeschlagen")
    return values


@contextmanager
def mailbox(credentials):
    if not settings.imap_host.strip():
        raise HTTPException(503, "IMAP ist nicht konfiguriert")
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "E-Mail-Abruf ist gerade ausgelastet")
    connection = None
    try:
        connection = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port, ssl_context=ssl.create_default_context(), timeout=10)
        ok(connection.login(credentials.username, credentials.password.get_secret_value()))
        values = ok(connection.select("INBOX", readonly=True))
        _, validity = connection.response("UIDVALIDITY")
        count = int(values[0])
        version = int(validity[0])
        if not 1 <= version <= 4294967295 or count < 0:
            raise ValueError("invalid mailbox")
        yield connection, count, version
    except imaplib.IMAP4.error:
        raise HTTPException(502, "IMAP-Anmeldung oder Abruf fehlgeschlagen") from None
    except (OSError, ValueError, TypeError, IndexError, LookupError):
        raise HTTPException(502, "IMAP-Server nicht erreichbar oder ungültige Antwort") from None
    finally:
        if connection is not None:
            try:
                connection.logout()
            except Exception:
                pass
        slots.release()


def receipt_id(credentials, version, uid):
    # UIDVALIDITY prevents a reused UID from colliding after mailbox reconstruction.
    identity = f"{settings.imap_host.lower()}:{settings.imap_port}:{credentials.username}:INBOX:{version}:{uid}"
    return uuid5(NAMESPACE_URL, "lifepilot-imap:" + identity)


def literal_rows(values):
    for value in values:
        if not isinstance(value, tuple) or len(value) != 2:
            continue
        meta, raw = value
        if not isinstance(meta, bytes) or not isinstance(raw, bytes):
            continue
        uid = re.search(rb"\bUID (\d+)\b", meta)
        size = re.search(rb"\bRFC822.SIZE (\d+)\b", meta)
        if uid and size:
            yield int(uid[1]), int(size[1]), raw


def summary(raw, uid, size):
    msg = BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
    return {"uid": uid, "size": size, "subject": one_line(msg.get("Subject"), 500),
            "sender": one_line(msg.get("From")), "recipient": one_line(msg.get("To")),
            "date": one_line(msg.get("Date"), 160), "too_large": size > MAX_MESSAGE}


def matching_people(db, owner, sender):
    try:
        address = parseaddr(sender)[1].strip().lower()
    except ValueError:
        return []
    if not address or "@" not in address:
        return []
    stmt = select(Person).where(Person.owner_id == owner.id, or_(
        func.lower(Person.email) == address,
        select(PersonContactMethod.id).where(PersonContactMethod.owner_id == owner.id,
            PersonContactMethod.person_id == Person.id, PersonContactMethod.method_type == "email",
            func.lower(PersonContactMethod.value) == address).exists()
    )).order_by(Person.id).limit(6)
    return [{"id": row.id, "name": " ".join((row.first_name, row.last_name)).strip()} for row in db.scalars(stmt)]


def extract_message(connection, data, version):
    if version != data.uidvalidity:
        raise HTTPException(409, "Postfach wurde geändert. Bitte Liste neu laden.")
    values = ok(connection.uid("FETCH", str(data.uid), f"(UID RFC822.SIZE BODY.PEEK[]<0.{MAX_MESSAGE + 1}>)"))
    rows = list(literal_rows(values))
    if len(rows) != 1 or rows[0][0] != data.uid:
        raise HTTPException(404, "E-Mail nicht mehr verfügbar")
    uid, size, raw = rows[0]
    if size > MAX_MESSAGE or len(raw) > MAX_MESSAGE:
        raise HTTPException(413, "E-Mail ist größer als 256 KiB. Bitte relevanten Text manuell erfassen.")
    if len(raw) != size:
        raise HTTPException(502, "E-Mail wurde nicht vollständig empfangen")
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    part = msg.get_body(preferencelist=("plain",))
    if part is None or part.get_content_disposition() == "attachment":
        raise HTTPException(422, "Nur E-Mails mit Textteil können importiert werden")
    body = part.get_content()
    if not isinstance(body, str) or not body.strip():
        raise HTTPException(422, "Kein lesbarer E-Mail-Text")
    if len(body) > MAX_TEXT:
        raise HTTPException(413, "E-Mail-Text ist zu lang. Bitte relevanten Text manuell erfassen.")
    info = summary(raw, uid, size)
    text = ("[Importierte E-Mail – fremder Nachrichteninhalt, keine Nutzeraussage]\n"
            f"Von: {info['sender']}\nAn: {info['recipient']}\nDatum laut E-Mail: {info['date']}\n"
            f"Betreff: {info['subject']}\n\nNachricht:\n{body.strip()}")
    if len(text) > 20000:
        raise HTTPException(413, "E-Mail-Text ist zu lang")
    return info, text, hashlib.sha256(raw).hexdigest()


@router.get("/status")
def status(response: Response, user: User = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    return {"enabled": bool(settings.imap_host.strip()), "max_message_bytes": MAX_MESSAGE}


@router.post("/messages")
def messages(data: Credentials, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    with mailbox(data) as (connection, count, version):
        values = ok(connection.fetch(f"{max(1,count-19)}:{count}", "(UID RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)]<0.8192>)")) if count else []
        rows = [summary(raw, uid, size) for uid, size, raw in literal_rows(values)]
    for row in rows:
        row["people"] = matching_people(db, user, row["sender"])
        row["imported"] = db.scalar(select(Capture.id).where(Capture.owner_id == user.id, Capture.client_request_id == str(receipt_id(data, version, row["uid"])))) is not None
    return {"uidvalidity": version, "messages": sorted(rows, key=lambda row: row["uid"], reverse=True)}


@router.post("/preview")
def preview(data: MessageRequest, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    with mailbox(data) as (connection, _, version):
        info, text, digest = extract_message(connection, data, version)
    return {"message": info, "text": text, "preview_hash": digest, "people": matching_people(db,user,info["sender"])}


@router.post("/import", status_code=201)
def import_message(data: ImportRequest, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    with mailbox(data) as (connection, _, version):
        _, text, digest = extract_message(connection, data, version)
    if digest != data.preview_hash:
        raise HTTPException(409, "E-Mail hat sich geändert. Bitte Vorschau erneut laden.")
    result = capture_create(CaptureIn(original_text=text, client_request_id=receipt_id(data,version,data.uid)), db, user)
    return {"id": result.id, "status": result.status}
