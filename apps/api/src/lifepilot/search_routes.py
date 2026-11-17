from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import get_db
from lifepilot.embedding_jobs import enqueue_memory_embedding
from lifepilot.entity_embedding_jobs import EntityType, enqueue_entity_embedding
from lifepilot.embeddings import embedding_provider_configured
from lifepilot.models import Conversation, Memory, Project, Relationship, Task, User
from lifepilot.schemas import ReindexOut
from lifepilot.security import current_user

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("/reindex", response_model=ReindexOut, status_code=202)
def memory_reindex(db: Session = Depends(get_db), user: User = Depends(current_user)) -> ReindexOut:
    if not embedding_provider_configured():
        raise HTTPException(status_code=409, detail="Bitte zuerst Embedding-Modell und API-Adresse konfigurieren")
    if not settings.redis_url:
        raise HTTPException(status_code=503, detail="Der Hintergrunddienst ist nicht konfiguriert")
    memories = db.scalars(select(Memory).where(Memory.owner_id == user.id)).all()
    queued = sum(enqueue_memory_embedding(memory.id, user.id) for memory in memories)
    failed = len(memories) - queued
    records: tuple[tuple[EntityType, list[Conversation] | list[Task] | list[Relationship] | list[Project]], ...] = (
        ("conversation", list(db.scalars(select(Conversation).where(Conversation.owner_id == user.id)).all())),
        ("task", list(db.scalars(select(Task).where(Task.owner_id == user.id)).all())),
        ("relationship", list(db.scalars(select(Relationship).where(Relationship.owner_id == user.id)).all())),
        ("project", list(db.scalars(select(Project).where(Project.owner_id == user.id)).all())),
    )
    for entity_type, rows in records:
        for row in rows:
            if enqueue_entity_embedding(entity_type, row.id, user.id):
                queued += 1
            else:
                failed += 1
    if failed and not queued:
        raise HTTPException(status_code=503, detail="Der Hintergrunddienst ist nicht erreichbar")
    return ReindexOut(queued=queued, failed=failed, semantic_enabled=True)
