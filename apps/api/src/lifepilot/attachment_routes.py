import io
import mimetypes
import stat
import re
import zipfile
import zlib
import struct
from pathlib import Path
from typing import Final, assert_never
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.responses import FileResponse

from lifepilot.file_security import MAX_ATTACHMENT_BYTES, storage_path, store_new, inspect_image
from lifepilot.db import get_db
from lifepilot.models import Attachment, DocumentIndex, DocumentPage, AuditEvent, Conversation, Event, Memory, Person, Project, User
from lifepilot.schemas import AttachmentOut, AttachmentResourceType
from lifepilot.security import current_user

router = APIRouter()
ALLOWED_EXTENSIONS: Final = frozenset({".pdf", ".txt", ".md", ".csv", ".jpg", ".jpeg", ".png", ".webp", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"})
OFFICE_EXTENSIONS: Final = frozenset({".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"})
CONTROL_CHARS: Final = re.compile(r"[\x00-\x1f\x7f]")


def attachment_path(owner_id: str, storage_key: str) -> Path:
    return storage_path("attachments",storage_key,owner_id)


def owned_attachment_resource(db: Session, resource_type: AttachmentResourceType, resource_id: str, user: User) -> None:
    match resource_type:
        case "person":
            exists = db.scalar(select(Person.id).where(Person.id == resource_id, Person.owner_id == user.id))
        case "memory":
            exists = db.scalar(select(Memory.id).where(Memory.id == resource_id, Memory.owner_id == user.id))
        case "conversation":
            exists = db.scalar(select(Conversation.id).where(Conversation.id == resource_id, Conversation.owner_id == user.id))
        case "event":
            exists = db.scalar(select(Event.id).where(Event.id == resource_id, Event.owner_id == user.id))
        case "project":
            exists = db.scalar(select(Project.id).where(Project.id == resource_id, Project.owner_id == user.id))
        case unreachable:
            assert_never(unreachable)
    if exists is None:
        raise HTTPException(status_code=404, detail="Zugehöriger Eintrag nicht gefunden")


def remove_document_index(db: Session, row: Attachment) -> None:
    db.execute(delete(DocumentPage).where(DocumentPage.document_id == row.id, DocumentPage.owner_id == row.owner_id))
    db.execute(delete(DocumentIndex).where(DocumentIndex.id == row.id, DocumentIndex.owner_id == row.owner_id))


def attachment_files_for_resource(db: Session, owner_id: str, resource_type: AttachmentResourceType, resource_id: str) -> list[Path]:
    rows = db.scalars(select(Attachment).where(Attachment.owner_id == owner_id, Attachment.resource_type == resource_type, Attachment.resource_id == resource_id)).all()
    paths = [attachment_path(owner_id, row.storage_key) for row in rows]
    for row in rows:
        remove_document_index(db, row)
        db.delete(row)
    return paths


def attachment_files_for_owner(db: Session, owner_id: str) -> list[Path]:
    rows = db.scalars(select(Attachment).where(Attachment.owner_id == owner_id)).all()
    paths = [attachment_path(owner_id, row.storage_key) for row in rows]
    for row in rows:
        remove_document_index(db, row)
        db.delete(row)
    return paths


def remove_attachment_files(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def safe_filename(filename: str | None) -> str:
    candidate = (filename or "").replace("\\", "/").split("/")[-1]
    cleaned = CONTROL_CHARS.sub("", candidate).strip().strip(".")
    if not cleaned:
        raise HTTPException(status_code=422, detail="Der Dateiname fehlt")
    suffix=Path(cleaned).suffix
    return cleaned[:240-len(suffix)]+suffix if len(cleaned)>240 and len(suffix)<=6 else cleaned[:240]


def validate_office(contents, suffix):
    roots={".docx":"word/document.xml",".xlsx":"xl/workbook.xml",".pptx":"ppt/presentation.xml"}
    mime={".odt":b"application/vnd.oasis.opendocument.text",".ods":b"application/vnd.oasis.opendocument.spreadsheet",".odp":b"application/vnd.oasis.opendocument.presentation"}
    try:
        # Bound the central directory before ZipFile allocates one object per entry.
        # ZIP64 and split archives are unnecessary for the accepted 20 MiB files.
        end=contents.rfind(b"PK\x05\x06",max(0,len(contents)-65557))
        if end<0 or len(contents)-end<22:
            raise ValueError()
        disk,cd_disk,disk_count,count,cd_size,cd_offset,comment=struct.unpack_from("<4H2IH",contents,end+4)
        if (disk or cd_disk or disk_count!=count or count>2048 or cd_size>4*1024*1024
            or cd_offset+cd_size!=end or end+22+comment!=len(contents)):
            raise ValueError()
        with zipfile.ZipFile(io.BytesIO(contents)) as archive:
            entries=archive.infolist()
            if len(entries)>2048:
                raise ValueError()
            names=set()
            total=0
            for entry in entries:
                name=entry.filename
                parts=name.rstrip("/").split("/")
                if (not name or any(p in ("",".","..") for p in parts) or "\\" in name or ":" in name
                    or CONTROL_CHARS.search(entry.orig_filename) or name.casefold() in names
                    or stat.S_ISLNK(entry.external_attr>>16) or entry.flag_bits&1
                    or entry.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED)):
                    raise ValueError()
                names.add(name.casefold())
                total+=entry.file_size
                if entry.file_size>32*1024*1024 or total>128*1024*1024 or entry.file_size>max(1024*1024,200*entry.compress_size):
                    raise ValueError()
                if name.lower().endswith("vbaproject.bin"):
                    raise ValueError()
            if suffix in roots:
                if not {"[Content_Types].xml",roots[suffix]}.issubset(archive.namelist()):
                    raise ValueError()
            else:
                if "content.xml" not in archive.namelist() or archive.getinfo("mimetype").file_size>128:
                    raise ValueError()
                if archive.read("mimetype")!=mime[suffix]:
                    raise ValueError()
    except (zipfile.BadZipFile,ValueError,KeyError,RuntimeError,NotImplementedError,OSError,EOFError,zlib.error,struct.error):
        raise HTTPException(415,"Office-Container ungültig oder Ressourcenlimit überschritten") from None


def validate_file(contents: bytes, filename: str) -> str:
    suffix=Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(415,"Dieser Dateityp wird nicht unterstützt")
    if not contents:
        raise HTTPException(422,"Die Datei ist leer")
    if suffix==".pdf" and not contents.startswith(b"%PDF-"):
        raise HTTPException(415,"Die Datei enthält kein erkennbares PDF")
    if suffix in {".txt",".md",".csv"}:
        try:
            value=contents.decode("utf-8-sig")
        except UnicodeError:
            raise HTTPException(415,"Textdatei muss UTF-8-kodiert sein") from None
        if any(ord(c)<32 and c not in "\r\n\t\f" for c in value) or "\x7f" in value:
            raise HTTPException(415,"Die Textdatei enthält ungültige Binärdaten")
    if suffix in OFFICE_EXTENSIONS:
        validate_office(contents,suffix)
    formats={".jpg":"JPEG",".jpeg":"JPEG",".png":"PNG",".webp":"WEBP"}
    if suffix in formats:
        return inspect_image(contents,formats[suffix])
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


@router.get("/api/attachments", response_model=list[AttachmentOut])
def attachment_list(resource_type: AttachmentResourceType, resource_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Attachment]:
    owned_attachment_resource(db, resource_type, resource_id, user)
    return list(db.scalars(select(Attachment).where(Attachment.owner_id == user.id, Attachment.resource_type == resource_type, Attachment.resource_id == resource_id).order_by(Attachment.created_at, Attachment.id)).all())


@router.post("/api/attachments", response_model=AttachmentOut, status_code=201)
async def attachment_upload(resource_type: AttachmentResourceType = Form(...), resource_id: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)) -> Attachment:
    owned_attachment_resource(db, resource_type, resource_id, user)
    filename = safe_filename(file.filename)
    contents = await file.read(MAX_ATTACHMENT_BYTES + 1)
    if len(contents) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="Eine Datei darf höchstens 20 MB groß sein")
    media_type = await run_in_threadpool(validate_file,contents,filename)
    storage_key = f"{uuid4().hex}{Path(filename).suffix.lower()}"
    path = attachment_path(user.id, storage_key)
    store_new(path,contents)
    row = Attachment(owner_id=user.id, resource_type=resource_type, resource_id=resource_id, storage_key=storage_key, file_name=filename, content_type=media_type, size_bytes=len(contents))
    try:
        db.add(row)
        db.flush()
        db.add(AuditEvent(owner_id=user.id, action="create", resource_type="attachments", resource_id=row.id, source="web"))
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    db.refresh(row)
    return row


@router.get("/api/attachments/{attachment_id}/download")
def attachment_download(attachment_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> FileResponse:
    row = db.scalar(select(Attachment).where(Attachment.id == attachment_id, Attachment.owner_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Anhang nicht gefunden")
    owned_attachment_resource(db, row.resource_type, row.resource_id, user)
    path = attachment_path(user.id, row.storage_key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Die gespeicherte Datei wurde nicht gefunden")
    return FileResponse(path, media_type=row.content_type, filename=row.file_name, content_disposition_type="attachment", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox; default-src 'none'"})


@router.delete("/api/attachments/{attachment_id}", status_code=204)
def attachment_delete(attachment_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    row = db.scalar(select(Attachment).where(Attachment.id == attachment_id, Attachment.owner_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Anhang nicht gefunden")
    path = attachment_path(user.id, row.storage_key)
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="attachments", resource_id=row.id, source="web"))
    remove_document_index(db, row)
    db.delete(row)
    db.commit()
    path.unlink(missing_ok=True)
