import hashlib
import logging

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue, Retry
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.embeddings import embed_text, embedding_provider_configured
from lifepilot.models import Memory, MemoryEmbedding
from lifepilot.scheduler import SCHEDULE_QUEUE_NAME

logger = logging.getLogger(__name__)


def enqueue_memory_embedding(memory_id: str, owner_id: str) -> bool:
    if not embedding_provider_configured() or not settings.redis_url:
        return False
    redis_client = Redis.from_url(settings.redis_url)
    try:
        Queue(SCHEDULE_QUEUE_NAME, connection=redis_client).enqueue(
            "lifepilot.embedding_jobs.process_memory_embedding",
            memory_id,
            owner_id,
            job_timeout=settings.embedding_timeout_seconds + 15,
            result_ttl=3600,
            failure_ttl=86400,
            retry=Retry(max=3, interval=[15, 60, 180]),
            description="Gedächtnisindex aktualisieren",
        )
        return True
    except RedisError:
        logger.exception("Embedding-Auftrag für Erinnerung %s konnte nicht eingereiht werden", memory_id)
        return False
    finally:
        redis_client.close()


def process_memory_embedding(memory_id: str, owner_id: str) -> str:
    with Session(engine) as db:
        memory = db.scalar(select(Memory).where(Memory.id == memory_id, Memory.owner_id == owner_id))
        if memory is None:
            return "missing"
        content_hash = hashlib.sha256(f"{memory.title}\n{memory.content}".encode()).hexdigest()
        row = db.get(MemoryEmbedding, memory.id)
        if row is not None and row.owner_id == owner_id and row.model == settings.embedding_model and row.content_hash == content_hash:
            return "unchanged"
        vector = embed_text(f"{memory.title}\n{memory.content}")
        if row is None:
            row = MemoryEmbedding(memory_id=memory.id, owner_id=owner_id, model=settings.embedding_model, content_hash=content_hash, embedding=vector)
            db.add(row)
        else:
            row.owner_id = owner_id
            row.model = settings.embedding_model
            row.content_hash = content_hash
            row.embedding = vector
        db.commit()
        return "indexed"
