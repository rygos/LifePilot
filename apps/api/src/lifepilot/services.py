from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from datetime import datetime
from fastapi import HTTPException
from zoneinfo import ZoneInfo
from lifepilot.models import Conversation, Gift, Loan, Memory, Person, Project, Relationship, Task, User
from lifepilot.schemas import ProjectIn, ProjectPatch

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

def search(db: Session, owner: User, query: str):
    term = f"%{query.strip()}%"
    people = db.scalars(select(Person).where(Person.owner_id == owner.id, or_(Person.first_name.ilike(term), Person.last_name.ilike(term), Person.nickname.ilike(term), Person.email.ilike(term), Person.phone.ilike(term), Person.address.ilike(term), Person.website.ilike(term), Person.job_title.ilike(term), Person.organization.ilike(term), Person.notes.ilike(term)))).all()
    memories = db.scalars(select(Memory).where(Memory.owner_id == owner.id, or_(Memory.title.ilike(term), Memory.content.ilike(term)))).all()
    tasks = db.scalars(select(Task).where(Task.owner_id == owner.id, or_(Task.title.ilike(term), Task.description.ilike(term)))).all()
    conversations = db.scalars(select(Conversation).where(Conversation.owner_id == owner.id, or_(Conversation.title.ilike(term), Conversation.original_note.ilike(term), Conversation.summary.ilike(term), Conversation.location.ilike(term)))).all()
    loans = db.scalars(select(Loan).where(Loan.owner_id == owner.id, Loan.item_name.ilike(term))).all()
    gifts = db.scalars(select(Gift).where(Gift.owner_id == owner.id, or_(Gift.title.ilike(term), Gift.note.ilike(term), Gift.occasion.ilike(term)))).all()
    return {"people": people, "memories": memories, "tasks": tasks, "conversations": conversations, "loans": loans, "gifts": gifts}

def relationship_create(db: Session, owner: User, source_id: str, target_id: str, relationship_type: str, source_memory_id: str | None, confirmed: bool, inverse_relationship_type: str | None = None):
    if source_id == target_id: raise HTTPException(status_code=422, detail="Eine Person kann nicht mit sich selbst verknüpft werden")
    owned_person(db, source_id, owner); owned_person(db, target_id, owner)
    if source_memory_id is not None and db.scalar(select(Memory.id).where(Memory.id == source_memory_id, Memory.owner_id == owner.id)) is None:
        raise HTTPException(status_code=404, detail="Quelle nicht gefunden")
    inverse = inverse_relationship_type or {"Tochter von": "Vater von", "Sohn von": "Vater von", "Vater von": "Tochter von", "Mutter von": "Tochter von", "Elternteil von": "Kind von", "Kind von": "Elternteil von", "kennt": "kennt", "Kollege von": "Kollege von"}.get(relationship_type, "Beziehung zu")
    existing = db.scalar(select(Relationship).where(Relationship.owner_id == owner.id, or_(and_(Relationship.source_person_id == source_id, Relationship.target_person_id == target_id, Relationship.relationship_type == relationship_type), and_(Relationship.source_person_id == target_id, Relationship.target_person_id == source_id, Relationship.relationship_type == inverse))))
    if existing is not None: raise HTTPException(status_code=409, detail="Diese Beziehung ist bereits gespeichert")
    row = Relationship(owner_id=owner.id, source_person_id=source_id, target_person_id=target_id, relationship_type=relationship_type, inverse_relationship_type=inverse, source_memory_id=source_memory_id, confirmed=confirmed)
    db.add(row); db.commit(); db.refresh(row)
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
    return project
