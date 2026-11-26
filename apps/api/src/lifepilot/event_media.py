from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import FileResponse

from lifepilot.file_security import MAX_PHOTO_BYTES, inspect_image, storage_path, store_new
from lifepilot.db import get_db
from lifepilot.models import AuditEvent, Event, EventPhoto, Person, User
from lifepilot.schemas import EventPhotoOut
from lifepilot.security import current_user

router = APIRouter()


def event_photo_files(db,owner,event_id=None):
    stmt=select(EventPhoto).where(EventPhoto.owner_id==owner)
    if event_id is not None:
        stmt=stmt.where(EventPhoto.event_id==event_id)
    rows=list(db.scalars(stmt))
    paths=[storage_path("event-photos",row.file_key) for row in rows]
    for row in rows:
        db.delete(row)
    return paths


def owner_photo_files(db,owner):
    keys=db.scalars(select(Person.photo_key).where(Person.owner_id==owner,Person.photo_key.is_not(None)))
    paths=[storage_path("people",key) for key in keys]
    return paths+event_photo_files(db,owner)


def owned_event(db: Session, event_id: str, user: User) -> Event:
    event = db.scalar(select(Event).where(Event.id == event_id, Event.owner_id == user.id))
    if event is None:
        raise HTTPException(status_code=404, detail="Ereignis nicht gefunden")
    return event


@router.get("/api/events/{event_id}/photos", response_model=list[EventPhotoOut])
def event_photo_list(event_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[EventPhoto]:
    owned_event(db, event_id, user)
    return list(db.scalars(select(EventPhoto).where(EventPhoto.event_id == event_id, EventPhoto.owner_id == user.id).order_by(EventPhoto.created_at, EventPhoto.id)).all())


@router.post("/api/events/{event_id}/photos", response_model=EventPhotoOut, status_code=201)
async def event_photo_upload(event_id: str, file: UploadFile = File(...), caption: str = Form(""), db: Session = Depends(get_db), user: User = Depends(current_user)) -> EventPhoto:
    owned_event(db, event_id, user)
    contents=await file.read(MAX_PHOTO_BYTES+1)
    if len(contents)>MAX_PHOTO_BYTES:
        raise HTTPException(413,"Das Bild darf höchstens 8 MiB groß sein")
    normalized=await run_in_threadpool(inspect_image,contents,normalize=True)
    file_key=f"{uuid4().hex}.jpg"
    path=storage_path("event-photos",file_key)
    store_new(path,normalized)
    photo=EventPhoto(owner_id=user.id,event_id=event_id,file_key=file_key,caption=caption.strip()[:240])
    try:
        db.add(photo)
        db.flush()
        db.add(AuditEvent(owner_id=user.id,action="create",resource_type="event_photos",resource_id=photo.id,source="web"))
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    db.refresh(photo)
    return photo


@router.get("/api/events/{event_id}/photos/{photo_id}/image")
def event_photo_get(event_id: str, photo_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> FileResponse:
    owned_event(db, event_id, user)
    photo = db.scalar(select(EventPhoto).where(EventPhoto.id == photo_id, EventPhoto.event_id == event_id, EventPhoto.owner_id == user.id))
    if photo is None:
        raise HTTPException(status_code=404, detail="Ereignisbild nicht gefunden")
    image_path = storage_path("event-photos",photo.file_key)
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Die Bilddatei wurde nicht gefunden")
    return FileResponse(image_path, media_type="image/jpeg", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/api/events/{event_id}/photos/{photo_id}", status_code=204)
def event_photo_delete(event_id: str, photo_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    owned_event(db, event_id, user)
    photo = db.scalar(select(EventPhoto).where(EventPhoto.id == photo_id, EventPhoto.event_id == event_id, EventPhoto.owner_id == user.id))
    if photo is None:
        raise HTTPException(status_code=404, detail="Ereignisbild nicht gefunden")
    image_path = storage_path("event-photos",photo.file_key)
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="event_photos", resource_id=photo.id, source="web"))
    db.delete(photo)
    db.commit()
    image_path.unlink(missing_ok=True)
