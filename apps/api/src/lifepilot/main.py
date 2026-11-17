from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from lifepilot.config import settings
from lifepilot.db import Base, engine, get_db
from lifepilot.audit import AuditEventView
from lifepilot.models import AuditEvent, Conversation, ConversationParticipant, Gift, Loan, Memory, Person, Relationship, Task, User
from lifepilot.schemas import ConversationIn, ConversationOut, Credentials, EventIn, GiftIn, GiftOut, LoanIn, LoanOut, MCPTokenRequest, MemoryIn, MemoryOut, PersonIn, PersonOut, ProfileOut, ProfileUpdate, RelationshipIn, RelationshipOut, TaskIn, TaskOut, Token
from lifepilot.security import create_token, current_user, hash_password, verify_password
from lifepilot.services import owned_person, relationship_create, search
from lifepilot.planner import router as planner_router
from lifepilot.capture_routes import router as capture_router
from lifepilot.project_routes import router as project_router
from lifepilot.approval_routes import router as approval_router
from lifepilot.embedding_jobs import enqueue_memory_embedding
from lifepilot.entity_embedding_jobs import delete_entity_embedding, enqueue_entity_embedding, enqueue_person_context_embeddings
from lifepilot.search_routes import router as search_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        if db.scalar(select(User).where(User.username == settings.life_pilot_bootstrap_username)) is None:
            db.add(User(username=settings.life_pilot_bootstrap_username, password_hash=hash_password(settings.life_pilot_bootstrap_password))); db.commit()
    yield

app = FastAPI(title="LifePilot", description="Dein persönliches digitales Gedächtnis", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.web_origin], allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])
app.include_router(planner_router)
app.include_router(capture_router)
app.include_router(project_router)
app.include_router(approval_router)
app.include_router(search_router)

@app.get("/health")
def health(): return {"status": "ok"}

@app.post("/api/auth/token", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == form.username))
    if user is None or not verify_password(form.password, user.password_hash): raise HTTPException(status_code=401, detail="Benutzername oder Passwort falsch")
    return {"access_token": create_token(user.id)}

@app.post("/api/auth/login", response_model=Token)
def login_json(data: Credentials, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == data.username))
    if user is None or not verify_password(data.password, user.password_hash): raise HTTPException(status_code=401, detail="Benutzername oder Passwort falsch")
    return {"access_token": create_token(user.id)}

@app.post("/api/auth/mcp-token", response_model=Token)
def mcp_token(data: MCPTokenRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == data.username))
    if user is None or not verify_password(data.password, user.password_hash): raise HTTPException(status_code=401, detail="Benutzername oder Passwort falsch")
    scopes = ["memory:read"]
    if data.access == "read_write": scopes.append("memory:write")
    return {"access_token": create_token(user.id, scopes, token_use="mcp")}

@app.get("/api/auth/me")
def me(user: User = Depends(current_user)): return {"id": user.id, "username": user.username}

@app.get("/api/profile", response_model=ProfileOut)
def profile_get(user: User = Depends(current_user)):
    return ProfileOut.model_validate(user)

@app.patch("/api/profile", response_model=ProfileOut)
def profile_update(data: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    for key, value in data.model_dump(exclude_unset=True).items(): setattr(user, key, value)
    db.commit(); db.refresh(user); return ProfileOut.model_validate(user)

@app.get("/api/people", response_model=list[PersonOut])
def people_list(db: Session = Depends(get_db), user: User = Depends(current_user), q: str = ""):
    stmt = select(Person).where(Person.owner_id == user.id)
    if q: stmt = stmt.where(or_(Person.first_name.ilike(f"%{q}%"), Person.last_name.ilike(f"%{q}%"), Person.nickname.ilike(f"%{q}%")))
    return db.scalars(stmt.order_by(Person.first_name, Person.last_name)).all()

@app.post("/api/people", response_model=PersonOut, status_code=201)
def person_create(data: PersonIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = Person(owner_id=user.id, **data.model_dump()); db.add(person); db.commit(); db.refresh(person); return person

@app.get("/api/people/{person_id}", response_model=PersonOut)
def person_get(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return owned_person(db, person_id, user)

@app.patch("/api/people/{person_id}", response_model=PersonOut)
def person_update(person_id: str, data: PersonIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user)
    for key, value in data.model_dump().items(): setattr(person, key, value)
    db.commit(); db.refresh(person)
    enqueue_person_context_embeddings(db, person.id, user.id)
    return person

@app.delete("/api/people/{person_id}", status_code=204)
def person_delete(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user); db.delete(person); db.commit()

@app.get("/api/relationships")
def relationship_list(db: Session = Depends(get_db), user: User = Depends(current_user), person_id: str | None = None):
    stmt = select(Relationship).where(Relationship.owner_id == user.id)
    if person_id:
        owned_person(db, person_id, user)
        stmt = stmt.where(or_(Relationship.source_person_id == person_id, Relationship.target_person_id == person_id))
    rows = db.scalars(stmt.order_by(Relationship.created_at.desc())).all()
    ids = {r.source_person_id for r in rows} | {r.target_person_id for r in rows}
    people_by_id = {p.id: p for p in db.scalars(select(Person).where(Person.owner_id == user.id, Person.id.in_(ids))).all()} if ids else {}
    return [RelationshipOut(id=r.id, source_person_id=r.source_person_id, source_person_name=f"{people_by_id[r.source_person_id].first_name} {people_by_id[r.source_person_id].last_name}".strip(), target_person_id=r.target_person_id, target_person_name=f"{people_by_id[r.target_person_id].first_name} {people_by_id[r.target_person_id].last_name}".strip(), relationship_type=r.relationship_type, inverse_relationship_type=r.inverse_relationship_type, confirmed=r.confirmed, source_memory_id=r.source_memory_id) for r in rows]

@app.post("/api/relationships", status_code=201)
def relationship_add(data: RelationshipIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return relationship_create(db, user, data.source_person_id, data.target_person_id, data.relationship_type, data.source_memory_id, data.confirmed, data.inverse_relationship_type)

@app.delete("/api/relationships/{relationship_id}", status_code=204)
def relationship_delete(relationship_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(Relationship).where(Relationship.id == relationship_id, Relationship.owner_id == user.id))
    if row is None: raise HTTPException(status_code=404, detail="Beziehung nicht gefunden")
    delete_entity_embedding(db, "relationship", row.id, user.id)
    db.delete(row); db.commit()

@app.post("/api/memories", response_model=MemoryOut, status_code=201)
def memory_create(data: MemoryIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_person(db, data.person_id, user)
    memory = Memory(owner_id=user.id, **data.model_dump()); db.add(memory); db.commit(); db.refresh(memory)
    enqueue_memory_embedding(memory.id, user.id)
    return memory

@app.get("/api/memories", response_model=list[MemoryOut])
def memory_list(db: Session = Depends(get_db), user: User = Depends(current_user), person_id: str | None = None, q: str = ""):
    stmt = select(Memory).where(Memory.owner_id == user.id)
    if person_id: stmt = stmt.where(Memory.person_id == person_id)
    if q: stmt = stmt.where(or_(Memory.title.ilike(f"%{q}%"), Memory.content.ilike(f"%{q}%")))
    return db.scalars(stmt.order_by(Memory.created_at.desc())).all()

@app.get("/api/search")
def memory_search(q: str = Query(min_length=1), db: Session = Depends(get_db), user: User = Depends(current_user)):
    return search(db, user, q)

@app.post("/api/conversations", response_model=ConversationOut, status_code=201)
def conversation_create(data: ConversationIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    participant_ids = list(dict.fromkeys(data.participant_ids))
    if participant_ids:
        people = db.scalars(select(Person).where(Person.owner_id == user.id, Person.id.in_(participant_ids))).all()
        if len(people) != len(participant_ids): raise HTTPException(status_code=404, detail="Mindestens eine beteiligte Person wurde nicht gefunden")
    conversation = Conversation(owner_id=user.id, title=data.title, original_note=data.original_note, summary=data.summary, location=data.location, occurred_at=data.occurred_at)
    db.add(conversation); db.flush()
    db.add_all(ConversationParticipant(conversation_id=conversation.id, person_id=person_id, owner_id=user.id) for person_id in participant_ids)
    db.commit(); db.refresh(conversation)
    enqueue_entity_embedding("conversation", conversation.id, user.id)
    return ConversationOut(id=conversation.id, title=conversation.title, original_note=conversation.original_note, summary=conversation.summary, location=conversation.location, occurred_at=conversation.occurred_at, created_at=conversation.created_at, participant_ids=participant_ids)

@app.get("/api/conversations", response_model=list[ConversationOut])
def conversation_list(db: Session = Depends(get_db), user: User = Depends(current_user), person_id: str | None = None, q: str = ""):
    stmt = select(Conversation).where(Conversation.owner_id == user.id)
    if person_id: stmt = stmt.join(ConversationParticipant).where(ConversationParticipant.person_id == person_id, ConversationParticipant.owner_id == user.id)
    if q: stmt = stmt.where(or_(Conversation.title.ilike(f"%{q}%"), Conversation.original_note.ilike(f"%{q}%"), Conversation.summary.ilike(f"%{q}%")))
    rows = db.scalars(stmt.order_by(Conversation.occurred_at.desc().nullslast(), Conversation.created_at.desc())).all()
    return [ConversationOut(id=row.id, title=row.title, original_note=row.original_note, summary=row.summary, location=row.location, occurred_at=row.occurred_at, created_at=row.created_at, participant_ids=list(db.scalars(select(ConversationParticipant.person_id).where(ConversationParticipant.conversation_id == row.id, ConversationParticipant.owner_id == user.id)).all())) for row in rows]

@app.post("/api/loans", response_model=LoanOut, status_code=201)
def loan_create(data: LoanIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_person(db, data.lender_person_id, user); owned_person(db, data.borrower_person_id, user)
    if data.lender_person_id is None and data.borrower_person_id is None: raise HTTPException(status_code=422, detail="Verleiher oder Entleiher muss angegeben sein")
    if data.source_memory_id and db.scalar(select(Memory.id).where(Memory.id == data.source_memory_id, Memory.owner_id == user.id)) is None: raise HTTPException(status_code=404, detail="Quellerinnerung nicht gefunden")
    loan = Loan(owner_id=user.id, **data.model_dump(exclude={"lent_at"}), lent_at=data.lent_at or datetime.now(timezone.utc))
    db.add(loan); db.commit(); db.refresh(loan); return loan

@app.get("/api/loans", response_model=list[LoanOut])
def loan_list(db: Session = Depends(get_db), user: User = Depends(current_user), open_only: bool = True, person_id: str | None = None):
    stmt = select(Loan).where(Loan.owner_id == user.id)
    if open_only: stmt = stmt.where(Loan.returned_at.is_(None))
    if person_id: stmt = stmt.where(or_(Loan.lender_person_id == person_id, Loan.borrower_person_id == person_id))
    return db.scalars(stmt.order_by(Loan.due_at.is_(None), Loan.due_at)).all()

@app.patch("/api/loans/{loan_id}/return", response_model=LoanOut)
def loan_return(loan_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loan = db.scalar(select(Loan).where(Loan.id == loan_id, Loan.owner_id == user.id))
    if loan is None: raise HTTPException(status_code=404, detail="Leihgabe nicht gefunden")
    if loan.returned_at is None: loan.returned_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(loan); return loan

@app.post("/api/gifts", response_model=GiftOut, status_code=201)
def gift_create(data: GiftIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_person(db, data.person_id, user)
    if data.source_memory_id and db.scalar(select(Memory.id).where(Memory.id == data.source_memory_id, Memory.owner_id == user.id)) is None: raise HTTPException(status_code=404, detail="Quellerinnerung nicht gefunden")
    gift = Gift(owner_id=user.id, **data.model_dump()); db.add(gift); db.commit(); db.refresh(gift); return gift

@app.get("/api/gifts", response_model=list[GiftOut])
def gift_list(db: Session = Depends(get_db), user: User = Depends(current_user), person_id: str | None = None):
    stmt = select(Gift).where(Gift.owner_id == user.id)
    if person_id: stmt = stmt.where(Gift.person_id == person_id)
    return db.scalars(stmt.order_by(Gift.created_at.desc())).all()

@app.get("/api/briefing/daily")
def daily_briefing(db: Session = Depends(get_db), user: User = Depends(current_user)):
    tasks = db.scalars(select(Task).where(Task.owner_id == user.id, Task.status == "open").order_by(Task.due_at).limit(10)).all()
    return {"open_tasks": [TaskOut.model_validate(t).model_dump(mode="json") for t in tasks]}

@app.get("/api/audit", response_model=list[AuditEventView])
def audit_list(db: Session = Depends(get_db), user: User = Depends(current_user), limit: int = Query(default=50, ge=1, le=200)) -> list[AuditEvent]:
    return list(db.scalars(select(AuditEvent).where(AuditEvent.owner_id == user.id).order_by(AuditEvent.created_at.desc()).limit(limit)).all())

@app.get("/api/briefing/person/{person_id}")
def person_briefing(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user)
    memories = db.scalars(select(Memory).where(Memory.owner_id == user.id, Memory.person_id == person_id).order_by(Memory.created_at.desc()).limit(10)).all()
    tasks = db.scalars(select(Task).where(Task.owner_id == user.id, Task.person_id == person_id, Task.status == "open")).all()
    links = db.scalars(select(Relationship).where(Relationship.owner_id == user.id, or_(Relationship.source_person_id == person_id, Relationship.target_person_id == person_id))).all()
    return {"person": PersonOut.model_validate(person), "memories": [MemoryOut.model_validate(m) for m in memories], "open_tasks": [TaskOut.model_validate(t) for t in tasks], "relationships": links}

try:
    from lifepilot.mcp_tools import mcp
except ImportError:
    mcp = None

def run_mcp():
    import uvicorn
    if mcp is None: raise RuntimeError("MCP SDK ist nicht verfügbar")
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=settings.mcp_port)
