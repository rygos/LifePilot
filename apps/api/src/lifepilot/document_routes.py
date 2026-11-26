"""Explicit local document extraction and page-grounded search."""
import hashlib
import os
import re
import shutil
import signal
import time
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import BoundedSemaphore
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from lifepilot.attachment_routes import attachment_path, owned_attachment_resource, MAX_ATTACHMENT_BYTES, validate_file
from lifepilot.capture_routes import capture_create
from lifepilot.capture_schemas import CaptureIn
from lifepilot.db import get_db
from lifepilot.models import Attachment, AuditEvent, DocumentIndex, DocumentPage, User, Person, Memory, Conversation, Event, Project
from lifepilot.security import current_user

router = APIRouter(prefix="/api/documents", tags=["Dokumentengedächtnis"])
MAX_PAGES = 10
MAX_CHARS = 10000
MAX_OCR_PAGES = 3
slots = BoundedSemaphore(1)
TEXT = {".txt", ".md", ".csv"}
IMAGES = {".jpg", ".jpeg", ".png", ".webp"}
SUPPORTED = TEXT | IMAGES | {".pdf"}
MARKER = "[Dokumentauszug – externe Quelle, keine Nutzeraussage]"
RESOURCES = {"person": Person, "memory": Memory, "conversation": Conversation, "event": Event, "project": Project}


class ExtractIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ocr: bool = False


class ImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1, le=MAX_PAGES)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    quote: str = Field(min_length=1, max_length=MAX_CHARS)


def owned(db, user, aid, lock=False):
    stmt = select(Attachment).where(Attachment.owner_id == user.id, Attachment.id == aid)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(404, "Anhang nicht gefunden")
    owned_attachment_resource(db, row.resource_type, row.resource_id, user)
    return row


def accessible(owner):
    return [((Attachment.resource_type == kind) & select(model.id).where(
        model.id == Attachment.resource_id, model.owner_id == owner).exists()) for kind, model in RESOURCES.items()]


def base_query(owner):
    from sqlalchemy import or_
    return select(Attachment, DocumentIndex).outerjoin(DocumentIndex, (DocumentIndex.id == Attachment.id) &
        (DocumentIndex.owner_id == owner)).where(Attachment.owner_id == owner, or_(*accessible(owner)))


def metadata(a, idx):
    return {"id":a.id,"file_name":a.file_name,"resource_type":a.resource_type,"resource_id":a.resource_id,
            "supported":Path(a.file_name).suffix.lower() in SUPPORTED,"indexed":idx is not None,
            "digest":idx.digest if idx else None,"partial":idx.partial if idx else None,
            "total_pages":idx.total_pages if idx else None,"indexed_at":idx.indexed_at if idx else None}


def list_documents(db, owner, limit=50, offset=0):
    return [metadata(a,i) for a,i in db.execute(base_query(owner).order_by(Attachment.created_at.desc(),Attachment.id).limit(limit).offset(offset))]


def run_local(args, directory, timeout=12):
    # Only approved installed tools; never pass the API/DB environment to parsers.
    if args[0] not in {"pdfinfo","pdftotext","pdftoppm","tesseract"}:
        raise ValueError("Unzulässiges Extraktionsprogramm")
    limiter=shutil.which("prlimit")
    executable=shutil.which(args[0])
    if not limiter or not executable:
        raise HTTPException(503,"Lokale Textextraktionsprogramme fehlen")
    output=Path(directory)/"output.txt"
    try:
        with output.open("wb") as stream:
            with subprocess.Popen([limiter,"--as=1073741824","--fsize=16777216","--cpu=12","--nofile=64","--core=0","--",executable,*args[1:]],
                cwd=directory,stdout=stream,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,start_new_session=True,
                env={"PATH":"/usr/bin:/bin","LC_ALL":"C","OMP_THREAD_LIMIT":"1","HOME":str(directory),"TMPDIR":str(directory)}) as proc:
                try:
                    if proc.wait(timeout=timeout)!=0:
                        raise subprocess.SubprocessError()
                except BaseException:
                    try:
                        os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
                    raise
        with output.open("rb") as stream:
            raw=stream.read(16*1024*1024+1)
        if len(raw)>16*1024*1024:
            raise ValueError()
        return raw.decode("utf-8",errors="replace")
    except (subprocess.SubprocessError,OSError,ValueError):
        raise HTTPException(422,"Lokale Textextraktion fehlgeschlagen (Format, Sprache oder Ressourcenlimit)") from None


def clean(value):
    return value.replace("\x00","").strip()


def extract_local(path, suffix, ocr, directory):
    deadline=time.monotonic()+45
    def run(args):
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise HTTPException(422,"Zeitlimit der Textextraktion überschritten")
        return run_local(args,directory,timeout=min(12,remaining))
    if suffix in TEXT:
        try:
            return 1, [(1, path.read_bytes().decode("utf-8-sig"), "text")]
        except UnicodeError:
            raise HTTPException(422,"Textdatei muss UTF-8-kodiert sein") from None
    def recognize(image):
        return run(["tesseract",str(image),"stdout","-l","deu+eng"])
    if suffix in IMAGES:
        if not ocr:
            raise HTTPException(422,"Für Bilder bitte OCR ausdrücklich aktivieren")
        return 1, [(1, recognize(path), "ocr")]
    info=run(["pdfinfo",str(path)])
    match=re.search(r"^Pages:\s+(\d+)\s*$",info,re.M)
    if not match or int(match[1])<1:
        raise HTTPException(422,"PDF-Seitenzahl nicht ermittelbar")
    total=int(match[1])
    pages=[]
    # One bounded extraction for the native text layer.
    raw=run(["pdftotext","-f","1","-l",str(min(total,MAX_PAGES)),"-enc","UTF-8",str(path),"-"])
    chunks=raw.split("\f")
    used=0
    for page in range(1,min(total,MAX_PAGES)+1):
        value=chunks[page-1] if page<=len(chunks) else ""
        method="pdf"
        if not clean(value) and ocr and used<MAX_OCR_PAGES:
            prefix=Path(directory)/"render"
            run(["pdftoppm","-f",str(page),"-l",str(page),"-scale-to","1800","-singlefile","-png",str(path),str(prefix)])
            value=recognize(prefix.with_suffix(".png"))
            method="ocr"
            used+=1
        pages.append((page,value,method))
    return total,pages


def read_document(db,user,aid):
    a=owned(db,user,aid)
    idx=db.scalar(select(DocumentIndex).where(DocumentIndex.id==aid,DocumentIndex.owner_id==user.id))
    result=metadata(a,idx)
    result["pages"]=[{"page":row.page,"text":row.content,"method":row.method,"truncated":row.truncated}
        for row in db.scalars(select(DocumentPage).where(DocumentPage.document_id==aid,DocumentPage.owner_id==user.id).order_by(DocumentPage.page))] if idx else []
    return result


def search_documents(db,owner,query,limit=30,offset=0):
    from sqlalchemy import or_
    if not query.strip() or len(query)>200 or not 1<=limit<=100 or offset<0:
        raise HTTPException(422,"Ungültige Suchanfrage")
    stmt=select(Attachment,DocumentIndex,DocumentPage).join(DocumentIndex,DocumentIndex.id==Attachment.id).join(DocumentPage,DocumentPage.document_id==DocumentIndex.id).where(
        Attachment.owner_id==owner,DocumentIndex.owner_id==owner,DocumentPage.owner_id==owner,
        or_(*accessible(owner)),DocumentPage.content.icontains(query.strip(),autoescape=True))
    results=[]
    for a,idx,row in db.execute(stmt.order_by(DocumentIndex.indexed_at.desc(),Attachment.id,DocumentPage.page).limit(limit).offset(offset)):
        position=max(0,row.content.lower().find(query.strip().lower()))
        results.append({**metadata(a,idx),"page":row.page,"snippet":row.content[max(0,position-100):position+len(query)+180],"method":row.method})
    return results


@router.get("")
def documents(limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),db:Session=Depends(get_db),user:User=Depends(current_user)):
    return list_documents(db,user.id,limit,offset)


@router.get("/search")
def search(q:str=Query(min_length=1,max_length=200),limit:int=Query(30,ge=1,le=100),offset:int=Query(0,ge=0),db:Session=Depends(get_db),user:User=Depends(current_user)):
    return search_documents(db,user.id,q,limit,offset)


@router.get("/{aid}")
def get_document(aid:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return read_document(db,user,aid)


@router.post("/{aid}/extract")
def extract(aid:str,data:ExtractIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=owned(db,user,aid,True)
    suffix=Path(a.file_name).suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(415,"Dateityp wird noch nicht indexiert")
    if not slots.acquire(blocking=False):
        raise HTTPException(429,"Textextraktion ist gerade ausgelastet")
    try:
        source=attachment_path(user.id,a.storage_key)
        if not source.is_file():
            raise HTTPException(404,"Originaldatei fehlt")
        with source.open("rb") as stream:
            contents=stream.read(MAX_ATTACHMENT_BYTES+1)
        if len(contents)>MAX_ATTACHMENT_BYTES:
            raise HTTPException(413,"Datei zu groß")
        validate_file(contents,a.file_name)
        digest=hashlib.sha256(contents).hexdigest()
        with tempfile.TemporaryDirectory(prefix="lifepilot-doc-") as directory:
            path=Path(directory)/("source"+suffix)
            path.write_bytes(contents)
            total,pages=extract_local(path,suffix,data.ocr,directory)
        idx=db.get(DocumentIndex,aid)
        if idx is not None and idx.owner_id!=user.id:
            raise HTTPException(404,"Dokument nicht gefunden")
        if idx is None:
            idx=DocumentIndex(id=aid,owner_id=user.id)
            db.add(idx)
        idx.digest=digest
        idx.total_pages=total
        idx.indexed_at=datetime.now(timezone.utc)
        idx.partial=total>len(pages) or any(not clean(value) or len(clean(value))>MAX_CHARS for _,value,_ in pages)
        db.flush()
        db.execute(delete(DocumentPage).where(DocumentPage.document_id==aid,DocumentPage.owner_id==user.id))
        for page,value,method in pages:
            value=clean(value)
            db.add(DocumentPage(document_id=aid,owner_id=user.id,page=page,content=value[:MAX_CHARS],method=method,truncated=len(value)>MAX_CHARS))
        db.add(AuditEvent(owner_id=user.id,action="update",resource_type="document_indexes",resource_id=aid,source="web"))
        db.commit()
        return read_document(db,user,aid)
    finally:
        slots.release()


@router.post("/{aid}/capture",status_code=201)
def import_excerpt(aid:str,data:ImportIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=owned(db,user,aid,True)
    idx=db.scalar(select(DocumentIndex).where(DocumentIndex.id==aid,DocumentIndex.owner_id==user.id))
    page=db.scalar(select(DocumentPage).where(DocumentPage.document_id==aid,DocumentPage.owner_id==user.id,DocumentPage.page==data.page))
    if idx is None or page is None or idx.digest!=data.digest:
        raise HTTPException(409,"Dokumentindex wurde geändert. Bitte neu laden.")
    if not data.quote.strip() or data.quote not in page.content:
        raise HTTPException(422,"Auszug muss wörtlich in der ausgewählten Seite stehen")
    text=f"{MARKER}\nAnhang-ID: {aid}\nDatei: {a.file_name}\nSeite: {data.page}\nSHA256: {idx.digest}\n\n{data.quote}"
    receipt=uuid5(NAMESPACE_URL,"lifepilot-document:"+aid+":"+idx.digest+":"+str(data.page)+":"+hashlib.sha256(data.quote.encode()).hexdigest())
    result=capture_create(CaptureIn(original_text=text,client_request_id=receipt),db,user)
    return {"id":result.id,"status":result.status}


@router.delete("/{aid}/index",status_code=204)
def remove_index(aid:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    owned(db,user,aid,True)
    db.execute(delete(DocumentPage).where(DocumentPage.document_id==aid,DocumentPage.owner_id==user.id))
    db.execute(delete(DocumentIndex).where(DocumentIndex.id==aid,DocumentIndex.owner_id==user.id))
    db.add(AuditEvent(owner_id=user.id,action="delete",resource_type="document_indexes",resource_id=aid,source="web"))
    db.commit()
