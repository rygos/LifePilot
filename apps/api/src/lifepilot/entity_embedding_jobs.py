import hashlib
import logging
import math
from dataclasses import dataclass
from typing import TypedDict, assert_never

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue, Retry
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.embeddings import EMBEDDING_DIMENSIONS, embed_text, embedding_provider_configured
from lifepilot.entity_types import EntityType
from lifepilot.models import Conversation, ConversationParticipant, ConversationProject, EntityEmbedding, Person, Project, Relationship, Task
from lifepilot.scheduler import SCHEDULE_QUEUE_NAME

logger = logging.getLogger(__name__)


class EntityMatches(TypedDict):
    conversation: list[str]
    task: list[str]
    relationship: list[str]
    project: list[str]


@dataclass(frozen=True, slots=True)
class EntityTargetIds:
    conversation_id: str | None = None
    task_id: str | None = None
    relationship_id: str | None = None
    project_id: str | None = None


def enqueue_entity_embedding(entity_type: EntityType, entity_id: str, owner_id: str) -> bool:
    if not embedding_provider_configured() or not settings.redis_url:
        return False
    redis_client = Redis.from_url(settings.redis_url)
    try:
        Queue(SCHEDULE_QUEUE_NAME, connection=redis_client).enqueue(
            "lifepilot.entity_embedding_jobs.process_entity_embedding",
            entity_type,
            entity_id,
            owner_id,
            job_timeout=settings.embedding_timeout_seconds + 15,
            result_ttl=3600,
            failure_ttl=86400,
            retry=Retry(max=3, interval=[15, 60, 180]),
            description="Eintrag im semantischen Suchindex aktualisieren",
        )
        return True
    except RedisError:
        logger.exception("Indexierungsauftrag für %s %s konnte nicht eingereiht werden", entity_type, entity_id)
        return False
    finally:
        redis_client.close()


def enqueue_person_context_embeddings(db: Session, person_id: str, owner_id: str) -> int:
    conversation_ids = db.scalars(
        select(ConversationParticipant.conversation_id).where(
            ConversationParticipant.person_id == person_id,
            ConversationParticipant.owner_id == owner_id,
        )
    ).all()
    task_ids = db.scalars(select(Task.id).where(Task.person_id == person_id, Task.owner_id == owner_id)).all()
    relationship_ids = db.scalars(select(Relationship.id).where(
        Relationship.owner_id == owner_id,
        (Relationship.source_person_id == person_id) | (Relationship.target_person_id == person_id),
    )).all()
    queued = 0
    for entity_id in conversation_ids:
        queued += enqueue_entity_embedding("conversation", entity_id, owner_id)
    for entity_id in task_ids:
        queued += enqueue_entity_embedding("task", entity_id, owner_id)
    for entity_id in relationship_ids:
        queued += enqueue_entity_embedding("relationship", entity_id, owner_id)
    return queued


def process_entity_embedding(entity_type: EntityType, entity_id: str, owner_id: str) -> str:
    with Session(engine) as db:
        text = _entity_text(db, entity_type, entity_id, owner_id)
        if text is None:
            return "missing"
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        row = db.scalar(select(EntityEmbedding).where(
            EntityEmbedding.owner_id == owner_id,
            EntityEmbedding.entity_type == entity_type,
            EntityEmbedding.entity_id == entity_id,
        ))
        if row is not None and row.model == settings.embedding_model and row.content_hash == content_hash:
            return "unchanged"
        target_ids = _target_ids(entity_type, entity_id)
        vector = embed_text(text)
        if row is None:
            row = EntityEmbedding(
                owner_id=owner_id,
                entity_type=entity_type,
                entity_id=entity_id,
                model=settings.embedding_model,
                content_hash=content_hash,
                embedding=vector,
                conversation_id=target_ids.conversation_id,
                task_id=target_ids.task_id,
                relationship_id=target_ids.relationship_id,
                project_id=target_ids.project_id,
            )
            db.add(row)
        else:
            row.model = settings.embedding_model
            row.content_hash = content_hash
            row.embedding = vector
        db.commit()
        return "indexed"


def delete_entity_embedding(db: Session, entity_type: EntityType, entity_id: str, owner_id: str) -> None:
    db.execute(delete(EntityEmbedding).where(
        EntityEmbedding.owner_id == owner_id,
        EntityEmbedding.entity_type == entity_type,
        EntityEmbedding.entity_id == entity_id,
    ))


def _target_ids(entity_type: EntityType, entity_id: str) -> EntityTargetIds:
    match entity_type:
        case "conversation": return EntityTargetIds(conversation_id=entity_id)
        case "task": return EntityTargetIds(task_id=entity_id)
        case "relationship": return EntityTargetIds(relationship_id=entity_id)
        case "project": return EntityTargetIds(project_id=entity_id)
        case unreachable: assert_never(unreachable)


def _entity_text(db: Session, entity_type: EntityType, entity_id: str, owner_id: str) -> str | None:
    match entity_type:
        case "conversation":
            row = db.scalar(select(Conversation).where(Conversation.id == entity_id, Conversation.owner_id == owner_id))
            if row is None:
                return None
            names = db.execute(
                select(Person.first_name, Person.last_name)
                .join(ConversationParticipant, ConversationParticipant.person_id == Person.id)
                .where(ConversationParticipant.conversation_id == row.id, ConversationParticipant.owner_id == owner_id, Person.owner_id == owner_id)
            ).all()
            people = ", ".join(" ".join(part for part in name if part) for name in names)
            projects = db.scalars(select(Project.name).join(ConversationProject, ConversationProject.project_id == Project.id).where(ConversationProject.conversation_id == row.id, ConversationProject.owner_id == owner_id, Project.owner_id == owner_id)).all()
            return "\n".join(part for part in (row.title, row.original_note, row.summary, row.location, row.occurred_at.isoformat() if row.occurred_at else "", people, ", ".join(projects)) if part)
        case "task":
            row = db.scalar(select(Task).where(Task.id == entity_id, Task.owner_id == owner_id))
            if row is None:
                return None
            person = db.scalar(select(Person).where(Person.id == row.person_id, Person.owner_id == owner_id)) if row.person_id else None
            name = " ".join(part for part in (person.first_name, person.last_name) if part) if person else ""
            project = db.scalar(select(Project).where(Project.id == row.project_id, Project.owner_id == owner_id)) if row.project_id else None
            return "\n".join(part for part in (row.title, row.description, row.status, row.due_at.isoformat() if row.due_at else "", name, project.name if project else "") if part)
        case "relationship":
            row = db.scalar(select(Relationship).where(Relationship.id == entity_id, Relationship.owner_id == owner_id))
            if row is None:
                return None
            people = db.scalars(select(Person).where(Person.owner_id == owner_id, Person.id.in_([row.source_person_id, row.target_person_id]))).all()
            by_id = {person.id: person for person in people}
            source = by_id.get(row.source_person_id)
            target = by_id.get(row.target_person_id)
            source_name = " ".join(part for part in (source.first_name, source.last_name) if part) if source else ""
            target_name = " ".join(part for part in (target.first_name, target.last_name) if part) if target else ""
            return "\n".join(part for part in (source_name, row.relationship_type, target_name, row.inverse_relationship_type, row.valid_from.isoformat() if row.valid_from else "", row.valid_until.isoformat() if row.valid_until else "") if part)
        case "project":
            row = db.scalar(select(Project).where(Project.id == entity_id, Project.owner_id == owner_id))
            if row is None:
                return None
            return "\n".join(part for part in (row.name, row.description, row.status) if part)
        case unreachable: assert_never(unreachable)


def semantic_entity_matches(db: Session, owner_id: str, model: str, query_vector: list[float]) -> EntityMatches:
    matches: EntityMatches = {"conversation": [], "task": [], "relationship": [], "project": []}
    if len(query_vector) != EMBEDDING_DIMENSIONS:
        return matches
    statement = select(EntityEmbedding).where(EntityEmbedding.owner_id == owner_id, EntityEmbedding.model == model)
    if db.get_bind().dialect.name == "postgresql":
        distance = EntityEmbedding.embedding.cosine_distance(query_vector)
        rows = db.scalars(statement.where(distance < 0.75).order_by(distance).limit(100)).all()
    else:
        query_length = math.sqrt(sum(value * value for value in query_vector))
        if query_length == 0:
            return matches
        scored: list[tuple[float, EntityEmbedding]] = []
        for row in db.scalars(statement).all():
            row_length = math.sqrt(sum(value * value for value in row.embedding))
            if row_length == 0:
                continue
            similarity = sum(left * right for left, right in zip(query_vector, row.embedding, strict=True)) / (query_length * row_length)
            if similarity >= 0.25:
                scored.append((similarity, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        rows = [row for _, row in scored[:100]]
    for row in rows:
        match row.entity_type:
            case "conversation": matches["conversation"].append(row.entity_id)
            case "task": matches["task"].append(row.entity_id)
            case "relationship": matches["relationship"].append(row.entity_id)
            case "project": matches["project"].append(row.entity_id)
            case unreachable: assert_never(unreachable)
    return matches
