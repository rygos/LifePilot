import math
from typing import TypedDict, assert_never
from sqlalchemy import and_, or_, select
from sqlalchemy import desc, func
from sqlalchemy.orm import Session
from datetime import datetime
from fastapi import HTTPException
from zoneinfo import ZoneInfo
from lifepilot.config import settings
from lifepilot.entity_embedding_jobs import enqueue_entity_embedding
from lifepilot.embeddings import EmbeddingProviderError, embed_text, embedding_provider_configured
from lifepilot.entity_embedding_jobs import EntityMatches, semantic_entity_matches
from lifepilot.entity_types import EntityType
from lifepilot.models import Conversation, Gift, Loan, Memory, MemoryEmbedding, MemoryProject, Person, PersonLifeEvent, PersonNameHistory, Project, Relationship, Task, User, UserPersonRelationship
from lifepilot.schemas import ProjectIn, ProjectPatch, RelationshipOut
from lifepilot.relationship_language import apply_relationship_gender

class SearchInfo(TypedDict):
    semantic_available: bool
    semantic_matches: int
    fulltext_used: bool

class SearchResults(TypedDict):
    people: list[Person]
    memories: list[Memory]
    tasks: list[Task]
    conversations: list[Conversation]
    loans: list[Loan]
    gifts: list[Gift]
    relationships: list[RelationshipOut]
    projects: list[Project]
    life_events: list[PersonLifeEvent]
    search_info: SearchInfo

def is_quiet_hours(owner: User, now: datetime) -> bool:
    if owner.quiet_hours_start is None or owner.quiet_hours_end is None:
        return False
    local_time = now.astimezone(ZoneInfo(owner.timezone_name)).time()
    start = owner.quiet_hours_start
    end = owner.quiet_hours_end
    if start < end:
        return start <= local_time < end
    return local_time >= start or local_time < end

def owned_person(db: Session, person_id: str | None, owner: User):
    if person_id is None: return None
    person = db.scalar(select(Person).where(Person.id == person_id, Person.owner_id == owner.id))
    if person is None: raise HTTPException(status_code=404, detail="Person nicht gefunden")
    return person

def owner_relationship_types(relationship_type: str) -> tuple[str, str]:
    role = " ".join(relationship_type.split())
    if role in {"Freund", "Freundin", "Freund von", "Freundin von"}:
        return "Freunde", "Freunde"
    inverse_by_role = {
        "Tochter von": "Elternteil von",
        "Sohn von": "Elternteil von",
        "Kind von": "Elternteil von",
        "Elternteil von": "Kind von",
        "Mutter von": "Kind von",
        "Vater von": "Kind von",
        "Partner von": "Partner von",
        "Ehepartner von": "Ehepartner von",
        "Geschwister von": "Geschwister von",
        "Bruder von": "Geschwister von",
        "Schwester von": "Geschwister von",
        "Freund": "Freunde",
        "Freundin": "Freunde",
        "Freund von": "Freunde",
        "Freundin von": "Freunde",
        "Freunde": "Freunde",
    }
    if role in inverse_by_role:
        return role, inverse_by_role[role]
    edge = role if role.endswith(" von") else f"{role} von"
    return edge, edge

def ensure_self_person(db: Session, owner: User) -> Person:
    person = db.scalar(select(Person).where(Person.owner_id == owner.id, Person.is_self.is_(True)))
    if person is not None:
        return person
    full_name = owner.full_name.strip()
    first_name, separator, last_name = full_name.partition(" ")
    person = Person(
        owner_id=owner.id,
        first_name=first_name or owner.username,
        last_name=last_name if separator else "",
        nickname=owner.nickname,
        birthday=owner.birthday,
        email=owner.email,
        phone=owner.phone,
        address=owner.address,
        is_self=True,
    )
    db.add(person)
    db.flush()
    return person

def sync_self_person_from_account(person: Person, owner: User) -> None:
    full_name = owner.full_name.strip()
    first_name, separator, last_name = full_name.partition(" ")
    person.first_name = first_name or owner.username
    person.last_name = last_name if separator else ""
    person.nickname = owner.nickname
    person.birthday = owner.birthday
    person.email = owner.email
    person.phone = owner.phone
    person.address = owner.address

def sync_account_from_self_person(person: Person, owner: User) -> None:
    owner.full_name = " ".join(part for part in (person.first_name.strip(), person.last_name.strip()) if part)
    owner.nickname = person.nickname
    owner.birthday = person.birthday
    owner.email = person.email
    owner.phone = person.phone
    owner.address = person.address

def search(db: Session, owner: User, query: str) -> SearchResults:
    term = f"%{query.strip()}%"
    alias_person_ids = select(PersonNameHistory.person_id).where(PersonNameHistory.owner_id == owner.id, PersonNameHistory.confirmed.is_(True), PersonNameHistory.name.ilike(term))
    owner_relation_ids = select(UserPersonRelationship.person_id).where(UserPersonRelationship.owner_id == owner.id, UserPersonRelationship.confirmed.is_(True), UserPersonRelationship.relationship_type.ilike(term))
    people = db.scalars(select(Person).where(Person.owner_id == owner.id, or_(Person.first_name.ilike(term), Person.last_name.ilike(term), Person.nickname.ilike(term), Person.email.ilike(term), Person.phone.ilike(term), Person.address.ilike(term), Person.website.ilike(term), Person.job_title.ilike(term), Person.organization.ilike(term), Person.notes.ilike(term), Person.id.in_(alias_person_ids), Person.id.in_(owner_relation_ids)))).all()
    project_ids = select(Project.id).where(Project.owner_id == owner.id, or_(Project.name.ilike(term), Project.description.ilike(term)))
    memory_ids = select(MemoryProject.memory_id).where(MemoryProject.owner_id == owner.id, MemoryProject.project_id.in_(project_ids))
    lexical_memories = list(db.scalars(select(Memory).where(Memory.owner_id == owner.id, or_(Memory.title.ilike(term), Memory.content.ilike(term), Memory.id.in_(memory_ids))).order_by(Memory.created_at.desc())).all())
    fulltext_ids = _postgres_fulltext_memory_ids(db, owner.id, query.strip())
    semantic_ids: list[str] = []
    entity_matches: EntityMatches = {"conversation": [], "task": [], "relationship": [], "project": []}
    semantic_available = False
    if embedding_provider_configured() and query.strip():
        try:
            query_vector = embed_text(query.strip())
            semantic_ids = _semantic_memory_ids(db, owner.id, query_vector)
            entity_matches = semantic_entity_matches(db, owner.id, settings.embedding_model, query_vector)
            semantic_available = True
        except EmbeddingProviderError:
            semantic_available = False
    ordered_ids = _rank_ids([ [row.id for row in lexical_memories], fulltext_ids, semantic_ids ])
    memory_map = {row.id: row for row in lexical_memories}
    if ordered_ids:
        missing_ids = [memory_id for memory_id in ordered_ids if memory_id not in memory_map]
        if missing_ids:
            memory_map.update({row.id: row for row in db.scalars(select(Memory).where(Memory.owner_id == owner.id, Memory.id.in_(missing_ids))).all()})
    memories = [memory_map[memory_id] for memory_id in ordered_ids if memory_id in memory_map]
    lexical_tasks = list(db.scalars(select(Task).where(Task.owner_id == owner.id, or_(Task.title.ilike(term), Task.description.ilike(term)))).all())
    fulltext_tasks = _postgres_fulltext_entity_ids(db, owner.id, query.strip(), "task")
    task_ids = _rank_ids([[row.id for row in lexical_tasks], fulltext_tasks, entity_matches["task"]])
    task_map = {row.id: row for row in lexical_tasks}
    if task_ids:
        missing_ids = [entity_id for entity_id in task_ids if entity_id not in task_map]
        task_map.update({row.id: row for row in db.scalars(select(Task).where(Task.owner_id == owner.id, Task.id.in_(missing_ids))).all()})
    tasks = [task_map[entity_id] for entity_id in task_ids if entity_id in task_map]
    lexical_conversations = list(db.scalars(select(Conversation).where(Conversation.owner_id == owner.id, or_(Conversation.title.ilike(term), Conversation.original_note.ilike(term), Conversation.summary.ilike(term), Conversation.location.ilike(term)))).all())
    fulltext_conversations = _postgres_fulltext_entity_ids(db, owner.id, query.strip(), "conversation")
    conversation_ids = _rank_ids([[row.id for row in lexical_conversations], fulltext_conversations, entity_matches["conversation"]])
    conversation_map = {row.id: row for row in lexical_conversations}
    if conversation_ids:
        missing_ids = [entity_id for entity_id in conversation_ids if entity_id not in conversation_map]
        conversation_map.update({row.id: row for row in db.scalars(select(Conversation).where(Conversation.owner_id == owner.id, Conversation.id.in_(missing_ids))).all()})
    conversations = [conversation_map[entity_id] for entity_id in conversation_ids if entity_id in conversation_map]
    loans = db.scalars(select(Loan).where(Loan.owner_id == owner.id, Loan.item_name.ilike(term))).all()
    gifts = db.scalars(select(Gift).where(Gift.owner_id == owner.id, or_(Gift.title.ilike(term), Gift.note.ilike(term), Gift.occasion.ilike(term)))).all()
    lexical_projects = list(db.scalars(select(Project).where(Project.owner_id == owner.id, or_(Project.name.ilike(term), Project.description.ilike(term))).order_by(Project.updated_at.desc())).all())
    project_ids = _rank_ids([[row.id for row in lexical_projects], _postgres_fulltext_entity_ids(db, owner.id, query.strip(), "project"), entity_matches["project"]])
    project_map = {row.id: row for row in lexical_projects}
    if project_ids:
        missing_ids = [entity_id for entity_id in project_ids if entity_id not in project_map]
        project_map.update({row.id: row for row in db.scalars(select(Project).where(Project.owner_id == owner.id, Project.id.in_(missing_ids))).all()})
    projects = [project_map[entity_id] for entity_id in project_ids if entity_id in project_map]
    life_events = db.scalars(select(PersonLifeEvent).where(PersonLifeEvent.owner_id == owner.id, PersonLifeEvent.confirmed.is_(True), or_(PersonLifeEvent.title.ilike(term), PersonLifeEvent.details.ilike(term))).order_by(PersonLifeEvent.occurred_at.desc().nullslast()).limit(20)).all()
    lexical_relationships = _lexical_relationships(db, owner.id, term)
    relationship_ids = _rank_ids([[row.id for row in lexical_relationships], _postgres_fulltext_entity_ids(db, owner.id, query.strip(), "relationship"), entity_matches["relationship"]])
    relationship_map = {row.id: row for row in lexical_relationships}
    if relationship_ids:
        missing_ids = [entity_id for entity_id in relationship_ids if entity_id not in relationship_map]
        relationship_map.update({row.id: row for row in db.scalars(select(Relationship).where(Relationship.owner_id == owner.id, Relationship.id.in_(missing_ids))).all()})
    relationships = [relationship_map[entity_id] for entity_id in relationship_ids if entity_id in relationship_map]
    related_ids = {person_id for row in relationships for person_id in (row.source_person_id, row.target_person_id)}
    if related_ids:
        people_map = {row.id: row for row in people}
        people_map.update({row.id: row for row in db.scalars(select(Person).where(Person.owner_id == owner.id, Person.id.in_(related_ids))).all()})
        people = list(people_map.values())
    people_by_id = {person.id: person for person in people}
    relationship_views = [RelationshipOut(
        id=row.id,
        source_person_id=row.source_person_id,
        source_person_name=f"{people_by_id[row.source_person_id].first_name} {people_by_id[row.source_person_id].last_name}".strip(),
        target_person_id=row.target_person_id,
        target_person_name=f"{people_by_id[row.target_person_id].first_name} {people_by_id[row.target_person_id].last_name}".strip(),
        relationship_type=row.relationship_type,
        inverse_relationship_type=row.inverse_relationship_type,
        confirmed=row.confirmed,
        source_memory_id=row.source_memory_id,
    ) for row in relationships]
    return {"people": people, "memories": memories, "tasks": tasks, "conversations": conversations, "loans": loans, "gifts": gifts, "relationships": relationship_views, "projects": projects, "life_events": life_events, "search_info": {"semantic_available": semantic_available, "semantic_matches": len(semantic_ids) + sum(map(len, entity_matches.values())), "fulltext_used": db.get_bind().dialect.name == "postgresql"}}


def _rank_ids(groups: list[list[str]]) -> list[str]:
    scores: dict[str, float] = {}
    for group in groups:
        for rank, entity_id in enumerate(group, start=1):
            scores[entity_id] = scores.get(entity_id, 0.0) + 1 / (60 + rank)
    return sorted(scores, key=scores.__getitem__, reverse=True)


def _lexical_relationships(db: Session, owner_id: str, term: str) -> list[Relationship]:
    from sqlalchemy.orm import aliased

    source = aliased(Person)
    target = aliased(Person)
    return list(db.scalars(
        select(Relationship)
        .join(source, source.id == Relationship.source_person_id)
        .join(target, target.id == Relationship.target_person_id)
        .where(
            Relationship.owner_id == owner_id,
            source.owner_id == owner_id,
            target.owner_id == owner_id,
            or_(source.first_name.ilike(term), source.last_name.ilike(term), target.first_name.ilike(term), target.last_name.ilike(term), Relationship.relationship_type.ilike(term), Relationship.inverse_relationship_type.ilike(term)),
        )
    ).all())


def _postgres_fulltext_entity_ids(db: Session, owner_id: str, query: str, entity_type: EntityType) -> list[str]:
    if db.get_bind().dialect.name != "postgresql" or not query:
        return []
    parsed_query = func.websearch_to_tsquery("simple", query)
    match entity_type:
        case "conversation":
            document = func.to_tsvector("simple", func.concat_ws(" ", Conversation.title, Conversation.original_note, Conversation.summary, Conversation.location))
            statement = select(Conversation.id).where(Conversation.owner_id == owner_id)
        case "task":
            document = func.to_tsvector("simple", func.concat_ws(" ", Task.title, Task.description, Task.status))
            statement = select(Task.id).where(Task.owner_id == owner_id)
        case "project":
            document = func.to_tsvector("simple", func.concat_ws(" ", Project.name, Project.description, Project.status))
            statement = select(Project.id).where(Project.owner_id == owner_id)
        case "relationship":
            from sqlalchemy.orm import aliased

            source = aliased(Person)
            target = aliased(Person)
            document = func.to_tsvector("simple", func.concat_ws(" ", source.first_name, source.last_name, Relationship.relationship_type, Relationship.inverse_relationship_type, target.first_name, target.last_name))
            statement = select(Relationship.id).join(source, source.id == Relationship.source_person_id).join(target, target.id == Relationship.target_person_id).where(Relationship.owner_id == owner_id, source.owner_id == owner_id, target.owner_id == owner_id)
        case unreachable: assert_never(unreachable)
    rank = func.ts_rank_cd(document, parsed_query)
    statement = statement.where(document.op("@@")(parsed_query)).order_by(desc(rank)).limit(100)
    return list(db.scalars(statement).all())

def _postgres_fulltext_memory_ids(db: Session, owner_id: str, query: str) -> list[str]:
    if db.get_bind().dialect.name != "postgresql" or not query:
        return []
    document = func.to_tsvector("simple", func.concat_ws(" ", Memory.title, Memory.content))
    parsed_query = func.websearch_to_tsquery("simple", query)
    rank = func.ts_rank_cd(document, parsed_query)
    statement = select(Memory.id).where(Memory.owner_id == owner_id, document.op("@@")(parsed_query)).order_by(desc(rank), Memory.created_at.desc()).limit(100)
    return list(db.scalars(statement).all())

def _semantic_memory_ids(db: Session, owner_id: str, query_vector: list[float]) -> list[str]:
    statement = select(MemoryEmbedding).where(MemoryEmbedding.owner_id == owner_id, MemoryEmbedding.model == settings.embedding_model)
    if db.get_bind().dialect.name == "postgresql":
        return list(db.scalars(select(MemoryEmbedding.memory_id).where(MemoryEmbedding.owner_id == owner_id).order_by(MemoryEmbedding.embedding.cosine_distance(query_vector)).limit(20)).all())
    query_length = math.sqrt(sum(value * value for value in query_vector))
    if query_length == 0:
        return []
    scored = []
    for row in db.scalars(statement).all():
        row_length = math.sqrt(sum(value * value for value in row.embedding))
        if row_length == 0:
            continue
        similarity = sum(left * right for left, right in zip(query_vector, row.embedding, strict=True)) / (query_length * row_length)
        if similarity >= 0.25:
            scored.append((similarity, row.memory_id))
    scored.sort(reverse=True)
    return [memory_id for _, memory_id in scored[:20]]

def relationship_create(db: Session, owner: User, source_id: str, target_id: str, relationship_type: str, source_memory_id: str | None, confirmed: bool, inverse_relationship_type: str | None = None, commit: bool = True):
    if source_id == target_id: raise HTTPException(status_code=422, detail="Eine Person kann nicht mit sich selbst verknüpft werden")
    source = owned_person(db, source_id, owner)
    target = owned_person(db, target_id, owner)
    if source_memory_id is not None and db.scalar(select(Memory.id).where(Memory.id == source_memory_id, Memory.owner_id == owner.id)) is None:
        raise HTTPException(status_code=404, detail="Quelle nicht gefunden")
    relationship_type, inverse = apply_relationship_gender(source, target, relationship_type, inverse_relationship_type)
    existing = db.scalar(select(Relationship).where(Relationship.owner_id == owner.id, or_(and_(Relationship.source_person_id == source_id, Relationship.target_person_id == target_id, Relationship.relationship_type == relationship_type), and_(Relationship.source_person_id == target_id, Relationship.target_person_id == source_id, Relationship.relationship_type == inverse))))
    if existing is not None: raise HTTPException(status_code=409, detail="Diese Beziehung ist bereits gespeichert")
    row = Relationship(owner_id=owner.id, source_person_id=source_id, target_person_id=target_id, relationship_type=relationship_type, inverse_relationship_type=inverse, source_memory_id=source_memory_id, confirmed=confirmed)
    db.add(row)
    if commit:
        db.commit(); db.refresh(row)
        enqueue_entity_embedding("relationship", row.id, owner.id)
    else:
        db.flush()
    return row

def project_list(db: Session, owner: User, query: str = "", status: str | None = None) -> list[Project]:
    statement = select(Project).where(Project.owner_id == owner.id)
    if query:
        term = f"%{query}%"
        statement = statement.where(or_(Project.name.ilike(term), Project.description.ilike(term)))
    if status is not None:
        statement = statement.where(Project.status == status)
    return list(db.scalars(statement.order_by(Project.updated_at.desc())).all())

def project_create(db: Session, owner: User, data: ProjectIn) -> Project:
    project = Project(owner_id=owner.id, **data.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    enqueue_entity_embedding("project", project.id, owner.id)
    return project

def project_get(db: Session, owner: User, project_id: str) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id, Project.owner_id == owner.id))
    if project is None:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    return project

def project_update(db: Session, owner: User, project_id: str, data: ProjectPatch) -> Project:
    project = project_get(db, owner, project_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(project, key, value)
    db.commit()
    db.refresh(project)
    enqueue_entity_embedding("project", project.id, owner.id)
    return project
