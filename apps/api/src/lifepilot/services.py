from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from lifepilot.models import Conversation, Gift, Loan, Memory, Person, Relationship, Task, User

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
