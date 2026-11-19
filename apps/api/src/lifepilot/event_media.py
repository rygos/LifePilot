import io
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import FileResponse

from lifepilot.config import settings
from lifepilot.db import get_db
from lifepilot.models import AuditEvent, Event, EventPhoto, User
from lifepilot.schemas import EventPhotoOut
from lifepilot.security import current_user

router = APIRouter()


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
    contents = await file.read(8 * 1024 * 1024 + 1)
    if len(contents) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Das Bild darf höchstens 8 MB groß sein")
    try:
        with Image.open(io.BytesIO(contents)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 40_000_000:
                raise HTTPException(status_code=415, detail="Bitte ein JPEG-, PNG- oder WebP-Bild unter 40 Megapixeln wählen")
            image.thumbnail((2048, 2048))
            output = io.BytesIO()
            image.convert("RGB").save(output, format="JPEG", quality=88, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(status_code=415, detail="Die Datei ist kein gültiges Bild") from None
    file_key = f"{uuid4().hex}.jpg"
    photo_directory = Path(settings.data_dir) / "event-photos"
    photo_directory.mkdir(parents=True, exist_ok=True)
    (photo_directory / file_key).write_bytes(output.getvalue())
    photo = EventPhoto(owner_id=user.id, event_id=event_id, file_key=file_key, caption=caption.strip()[:240])
    db.add(photo)
    db.flush()
    db.add(AuditEvent(owner_id=user.id, action="create", resource_type="event_photos", resource_id=photo.id, source="web"))
    db.commit()
    db.refresh(photo)
    return photo


@router.get("/api/events/{event_id}/photos/{photo_id}/image")
def event_photo_get(event_id: str, photo_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> FileResponse:
    owned_event(db, event_id, user)
    photo = db.scalar(select(EventPhoto).where(EventPhoto.id == photo_id, EventPhoto.event_id == event_id, EventPhoto.owner_id == user.id))
    if photo is None:
        raise HTTPException(status_code=404, detail="Ereignisbild nicht gefunden")
    image_path = Path(settings.data_dir) / "event-photos" / photo.file_key
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Die Bilddatei wurde nicht gefunden")
    return FileResponse(image_path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


@router.delete("/api/events/{event_id}/photos/{photo_id}", status_code=204)
def event_photo_delete(event_id: str, photo_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    owned_event(db, event_id, user)
    photo = db.scalar(select(EventPhoto).where(EventPhoto.id == photo_id, EventPhoto.event_id == event_id, EventPhoto.owner_id == user.id))
    if photo is None:
        raise HTTPException(status_code=404, detail="Ereignisbild nicht gefunden")
    image_path = Path(settings.data_dir) / "event-photos" / photo.file_key
    image_path.unlink(missing_ok=True)
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="event_photos", resource_id=photo.id, source="web"))
    db.delete(photo)
    db.commit()
