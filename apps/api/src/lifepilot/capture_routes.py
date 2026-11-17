from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from redis.exceptions import RedisError

from lifepilot.capture_jobs import enqueue_capture_job
from lifepilot.capture_schemas import AcceptedMemory, CaptureIn, CaptureOut, CaptureReview, CaptureSuggestion
from lifepilot.config import settings
from lifepilot.db import get_db
from lifepilot.embedding_jobs import enqueue_memory_embedding
from lifepilot.models import Capture, Memory, User
from lifepilot.security import current_user

router = APIRouter(prefix="/api/captures", tags=["Eingang"])
suggestion_list = TypeAdapter(list[CaptureSuggestion])


def capture_output(row: Capture) -> CaptureOut:
    return CaptureOut(
        id=row.id,
        original_text=row.original_text,
        status=row.status,
        suggestions=suggestion_list.validate_json(row.suggestions_json),
        processing_error=row.processing_error,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


@router.post("", response_model=CaptureOut, status_code=201)
def capture_create(data: CaptureIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> CaptureOut:
    row = Capture(owner_id=user.id, original_text=data.original_text.strip())
    if not row.original_text:
        raise HTTPException(status_code=422, detail="Die Eingabe darf nicht leer sein")
    db.add(row)
    db.commit()
    db.refresh(row)
    if settings.llm_base_url and settings.llm_model and settings.redis_url:
        try:
            enqueue_capture_job(row.id, user.id)
        except RedisError:
            row.status = "failed"
            row.processing_error = "Die Verarbeitungswarteschlange ist nicht erreichbar. Der Originaltext bleibt gespeichert."
    elif not settings.llm_base_url or not settings.llm_model:
        row.status = "unavailable"
        row.processing_error = "KI ist nicht konfiguriert. Der Originaltext wurde gespeichert."
    else:
        row.status = "failed"
        row.processing_error = "Redis ist für die KI-Warteschlange nicht konfiguriert. Der Originaltext bleibt gespeichert."
    db.commit()
    db.refresh(row)
    return capture_output(row)


@router.get("", response_model=list[CaptureOut])
def capture_list(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[CaptureOut]:
    rows = db.scalars(select(Capture).where(Capture.owner_id == user.id).order_by(Capture.created_at.desc()).limit(100)).all()
    return [capture_output(row) for row in rows]


@router.post("/{capture_id}/review", response_model=list[AcceptedMemory], status_code=201)
def capture_review(capture_id: str, data: CaptureReview, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[AcceptedMemory]:
    row = db.scalar(select(Capture).where(Capture.id == capture_id, Capture.owner_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Eingabe nicht gefunden")
    if row.status != "ready":
        raise HTTPException(status_code=409, detail="Diese Eingabe enthält keine prüfbaren Vorschläge")
    suggestions = suggestion_list.validate_json(row.suggestions_json)
    if len(set(data.accepted_indices)) != len(data.accepted_indices) or any(index < 0 or index >= len(suggestions) for index in data.accepted_indices):
        raise HTTPException(status_code=422, detail="Mindestens eine Vorschlagsauswahl ist ungültig")
    accepted = [suggestions[index] for index in data.accepted_indices]
    memories: list[Memory] = []
    for suggestion in accepted:
        memory = Memory(
            owner_id=user.id,
            title=suggestion.title,
            content=suggestion.content,
            source="capture",
            source_capture_id=row.id,
            occurred_at=suggestion.occurred_at,
        )
        memories.append(memory)
        db.add(memory)
    row.status = "reviewed"
    row.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    for memory in memories:
        enqueue_memory_embedding(memory.id, user.id)
    return [AcceptedMemory(id=memory.id, title=memory.title) for memory in memories]


@router.delete("/{capture_id}", status_code=204)
def capture_delete(capture_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    row = db.scalar(select(Capture).where(Capture.id == capture_id, Capture.owner_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Eingabe nicht gefunden")
    db.delete(row)
    db.commit()
