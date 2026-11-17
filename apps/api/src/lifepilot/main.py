from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import Session
from lifepilot.config import settings
from lifepilot.db import Base, engine, get_db
from lifepilot.models import Conversation, ConversationParticipant, Event, EventParticipant, Gift, Loan, Memory, Person, Relationship, Reminder, Task, User
from lifepilot.schemas import ConversationIn, ConversationOut, Credentials, EventIn, EventOut, GiftIn, GiftOut, LoanIn, LoanOut, MemoryIn, MemoryOut, PersonIn, PersonOut, ReminderAction, ReminderIn, ReminderOut, RelationshipIn, TaskIn, TaskOut, Token
from lifepilot.security import create_token, current_user, hash_password, verify_password
from lifepilot.security import resolve_bearer_user
from lifepilot.services import owned_person, relationship_create, search

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        if db.scalar(select(User).where(User.username == settings.life_pilot_bootstrap_username)) is None:
            db.add(User(username=settings.life_pilot_bootstrap_username, password_hash=hash_password(settings.life_pilot_bootstrap_password))); db.commit()
    yield

app = FastAPI(title="LifePilot", description="Dein persönliches digitales Gedächtnis", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.web_origin], allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])

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

@app.get("/api/auth/me")
def me(user: User = Depends(current_user)): return {"id": user.id, "username": user.username}

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
    db.commit(); db.refresh(person); return person

@app.delete("/api/people/{person_id}", status_code=204)
def person_delete(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user); db.delete(person); db.commit()

@app.get("/api/relationships")
def relationship_list(db: Session = Depends(get_db), user: User = Depends(current_user), person_id: str | None = None):
    stmt = select(Relationship).where(Relationship.owner_id == user.id)
    if person_id: stmt = stmt.where(or_(Relationship.source_person_id == person_id, Relationship.target_person_id == person_id))
    return db.scalars(stmt).all()

@app.post("/api/relationships", status_code=201)
def relationship_add(data: RelationshipIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return relationship_create(db, user, data.source_person_id, data.target_person_id, data.relationship_type, data.source_memory_id, data.confirmed)

@app.post("/api/memories", response_model=MemoryOut, status_code=201)
def memory_create(data: MemoryIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_person(db, data.person_id, user)
    memory = Memory(owner_id=user.id, **data.model_dump()); db.add(memory); db.commit(); db.refresh(memory); return memory

@app.get("/api/memories", response_model=list[MemoryOut])
def memory_list(db: Session = Depends(get_db), user: User = Depends(current_user), person_id: str | None = None, q: str = ""):
    stmt = select(Memory).where(Memory.owner_id == user.id)
    if person_id: stmt = stmt.where(Memory.person_id == person_id)
    if q: stmt = stmt.where(or_(Memory.title.ilike(f"%{q}%"), Memory.content.ilike(f"%{q}%")))
    return db.scalars(stmt.order_by(Memory.created_at.desc())).all()

@app.post("/api/tasks", response_model=TaskOut, status_code=201)
def task_create(data: TaskIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_person(db, data.person_id, user)
    task = Task(owner_id=user.id, **data.model_dump()); db.add(task); db.commit(); db.refresh(task); return task

@app.get("/api/tasks", response_model=list[TaskOut])
def task_list(db: Session = Depends(get_db), user: User = Depends(current_user), status: str | None = None):
    stmt = select(Task).where(Task.owner_id == user.id)
    if status: stmt = stmt.where(Task.status == status)
    return db.scalars(stmt.order_by(Task.due_at.is_(None), Task.due_at)).all()

@app.patch("/api/tasks/{task_id}/complete", response_model=TaskOut)
def task_complete(task_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    task = db.scalar(select(Task).where(Task.id == task_id, Task.owner_id == user.id))
    if task is None: raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
    task.status = "done"
    reminder = db.scalar(select(Reminder).where(Reminder.task_id == task.id, Reminder.owner_id == user.id, Reminder.state == "scheduled"))
    if reminder: reminder.state = "done"
    db.commit(); db.refresh(task); return task

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

def event_output(db: Session, event: Event, owner_id: str) -> EventOut:
    participant_ids = list(db.scalars(select(EventParticipant.person_id).where(EventParticipant.event_id == event.id, EventParticipant.owner_id == owner_id)).all())
    return EventOut(id=event.id, title=event.title, description=event.description, location=event.location, starts_at=event.starts_at, ends_at=event.ends_at, source_memory_id=event.source_memory_id, participant_ids=participant_ids)

@app.post("/api/events", response_model=EventOut, status_code=201)
def event_create(data: EventIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    participant_ids = list(dict.fromkeys(data.participant_ids))
    if participant_ids:
        valid_ids = set(db.scalars(select(Person.id).where(Person.owner_id == user.id, Person.id.in_(participant_ids))).all())
        if valid_ids != set(participant_ids): raise HTTPException(status_code=404, detail="Mindestens eine beteiligte Person wurde nicht gefunden")
    if data.source_memory_id and db.scalar(select(Memory.id).where(Memory.id == data.source_memory_id, Memory.owner_id == user.id)) is None: raise HTTPException(status_code=404, detail="Quellerinnerung nicht gefunden")
    if data.ends_at and data.ends_at < data.starts_at: raise HTTPException(status_code=422, detail="Das Ende muss nach dem Beginn liegen")
    event = Event(owner_id=user.id, **data.model_dump(exclude={"participant_ids"})); db.add(event); db.flush()
    db.add_all(EventParticipant(event_id=event.id, person_id=person_id, owner_id=user.id) for person_id in participant_ids)
    db.commit(); db.refresh(event); return event_output(db, event, user.id)

@app.get("/api/events", response_model=list[EventOut])
def event_list(db: Session = Depends(get_db), user: User = Depends(current_user), from_at: datetime | None = None, to_at: datetime | None = None, person_id: str | None = None):
    stmt = select(Event).where(Event.owner_id == user.id)
    if from_at: stmt = stmt.where(Event.starts_at >= from_at)
    if to_at: stmt = stmt.where(Event.starts_at <= to_at)
    if person_id: stmt = stmt.join(EventParticipant).where(EventParticipant.person_id == person_id, EventParticipant.owner_id == user.id)
    return [event_output(db, event, user.id) for event in db.scalars(stmt.order_by(Event.starts_at)).all()]

@app.post("/api/reminders", response_model=ReminderOut, status_code=201)
def reminder_create(data: ReminderIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if bool(data.task_id) == bool(data.event_id): raise HTTPException(status_code=422, detail="Eine Erinnerung muss genau einer Aufgabe oder einem Termin zugeordnet sein")
    if data.task_id and db.scalar(select(Task.id).where(Task.id == data.task_id, Task.owner_id == user.id)) is None: raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
    if data.event_id and db.scalar(select(Event.id).where(Event.id == data.event_id, Event.owner_id == user.id)) is None: raise HTTPException(status_code=404, detail="Termin nicht gefunden")
    row = Reminder(owner_id=user.id, **data.model_dump()); db.add(row); db.commit(); db.refresh(row); return row

@app.get("/api/reminders", response_model=list[ReminderOut])
def reminder_list(db: Session = Depends(get_db), user: User = Depends(current_user), state: str | None = None):
    stmt = select(Reminder).where(Reminder.owner_id == user.id)
    if state: stmt = stmt.where(Reminder.state == state)
    return db.scalars(stmt.order_by(Reminder.due_at)).all()

@app.get("/api/notifications", response_model=list[ReminderOut])
def notifications(db: Session = Depends(get_db), user: User = Depends(current_user)):
    now = datetime.now(timezone.utc)
    return db.scalars(select(Reminder).where(Reminder.owner_id == user.id, Reminder.state == "scheduled", or_(and_(Reminder.snoozed_until.is_(None), Reminder.due_at <= now), Reminder.snoozed_until <= now)).order_by(Reminder.due_at)).all()

@app.patch("/api/reminders/{reminder_id}", response_model=ReminderOut)
def reminder_update(reminder_id: str, data: ReminderAction, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if data.state not in {"scheduled", "done", "muted"}: raise HTTPException(status_code=422, detail="Ungültiger Erinnerungsstatus")
    row = db.scalar(select(Reminder).where(Reminder.id == reminder_id, Reminder.owner_id == user.id))
    if row is None: raise HTTPException(status_code=404, detail="Erinnerung nicht gefunden")
    row.state = data.state; row.snoozed_until = data.snoozed_until
    if data.snoozed_until: row.state = "scheduled"
    db.commit(); db.refresh(row); return row

@app.get("/api/briefing/daily")
def daily_briefing(db: Session = Depends(get_db), user: User = Depends(current_user)):
    tasks = db.scalars(select(Task).where(Task.owner_id == user.id, Task.status == "open").order_by(Task.due_at).limit(10)).all()
    return {"open_tasks": [TaskOut.model_validate(t).model_dump(mode="json") for t in tasks]}

@app.get("/api/briefing/person/{person_id}")
def person_briefing(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user)
    memories = db.scalars(select(Memory).where(Memory.owner_id == user.id, Memory.person_id == person_id).order_by(Memory.created_at.desc()).limit(10)).all()
    tasks = db.scalars(select(Task).where(Task.owner_id == user.id, Task.person_id == person_id, Task.status == "open")).all()
    links = db.scalars(select(Relationship).where(Relationship.owner_id == user.id, or_(Relationship.source_person_id == person_id, Relationship.target_person_id == person_id))).all()
    return {"person": PersonOut.model_validate(person), "memories": [MemoryOut.model_validate(m) for m in memories], "open_tasks": [TaskOut.model_validate(t) for t in tasks], "relationships": links}

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.auth.provider import AccessToken, TokenVerifier
    from mcp.server.auth.middleware.auth_context import get_access_token
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
    class LifePilotTokenVerifier(TokenVerifier):
        async def verify_token(self, token: str) -> AccessToken | None:
            with Session(engine) as db:
                try:
                    user = resolve_bearer_user(token, db)
                    return AccessToken(token=token, client_id=user.id, scopes=["memory:read", "memory:write"], resource="http://localhost/mcp/")
                except HTTPException:
                    return None
    mcp = FastMCP("LifePilot", token_verifier=LifePilotTokenVerifier(), auth=AuthSettings(issuer_url="http://localhost", resource_server_url="http://localhost/mcp/", required_scopes=["memory:read"], client_registration_options=ClientRegistrationOptions(enabled=False), revocation_options=RevocationOptions(enabled=False), validate_token_resource=False), stateless_http=True, json_response=True, streamable_http_path="/mcp")
    def mcp_user():
        token = get_access_token()
        if token is None: raise ValueError("Bearer token erforderlich")
        return token.client_id
    @mcp.tool()
    def person_create_tool(first_name: str, last_name: str = "", birthday: str | None = None, notes: str = "") -> dict:
        owner_id = mcp_user()
        with Session(engine) as db:
            row = Person(owner_id=owner_id, first_name=first_name, last_name=last_name, birthday=birthday, notes=notes); db.add(row); db.commit(); db.refresh(row)
            return PersonOut.model_validate(row).model_dump(mode="json")
    @mcp.tool()
    def person_search_tool(query: str) -> list[dict]:
        owner_id = mcp_user(); term = f"%{query}%"
        with Session(engine) as db:
            rows = db.scalars(select(Person).where(Person.owner_id == owner_id, or_(Person.first_name.ilike(term), Person.last_name.ilike(term), Person.notes.ilike(term)))).all()
            return [PersonOut.model_validate(r).model_dump(mode="json") for r in rows]
    @mcp.tool()
    def memory_capture_tool(title: str, content: str, person_id: str | None = None) -> dict:
        owner_id = mcp_user()
        with Session(engine) as db:
            user = db.get(User, owner_id); owned_person(db, person_id, user)
            row = Memory(owner_id=owner_id, person_id=person_id, title=title, content=content); db.add(row); db.commit(); db.refresh(row)
            return MemoryOut.model_validate(row).model_dump(mode="json")
    @mcp.tool()
    def memory_search_tool(query: str) -> dict:
        owner_id = mcp_user()
        with Session(engine) as db:
            user = db.get(User, owner_id); result = search(db, user, query)
            return {"people": [PersonOut.model_validate(x).model_dump(mode="json") for x in result["people"]], "memories": [MemoryOut.model_validate(x).model_dump(mode="json") for x in result["memories"]], "tasks": [TaskOut.model_validate(x).model_dump(mode="json") for x in result["tasks"]]}
except ImportError:
    pass

def run_mcp():
    import uvicorn
    if "mcp" not in globals(): raise RuntimeError("MCP SDK is unavailable")
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=settings.mcp_port)
