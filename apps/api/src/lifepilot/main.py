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
from lifepilot.models import Conversation, ConversationParticipant, Gift, Loan, Memory, Person, Relationship, Task, User
from lifepilot.schemas import ConversationIn, ConversationOut, Credentials, EventIn, GiftIn, GiftOut, LoanIn, LoanOut, MCPTokenRequest, MemoryIn, MemoryOut, PersonIn, PersonOut, ProfileOut, ProfileUpdate, RelationshipIn, RelationshipOut, TaskIn, TaskOut, Token
from lifepilot.security import create_token, current_user, hash_password, verify_password
from lifepilot.security import resolve_bearer_scopes, resolve_bearer_user
from lifepilot.services import owned_person, relationship_create, search
from lifepilot.planner import router as planner_router

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
    return {"access_token": create_token(user.id, scopes)}

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
    db.commit(); db.refresh(person); return person

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
    db.delete(row); db.commit()

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
                    return AccessToken(token=token, client_id=user.id, scopes=resolve_bearer_scopes(token), resource="http://localhost/mcp/")
                except HTTPException:
                    return None
    mcp = FastMCP("LifePilot", token_verifier=LifePilotTokenVerifier(), auth=AuthSettings(issuer_url="http://localhost", resource_server_url="http://localhost/mcp/", required_scopes=["memory:read"], client_registration_options=ClientRegistrationOptions(enabled=False), revocation_options=RevocationOptions(enabled=False), validate_token_resource=False), stateless_http=True, json_response=True, streamable_http_path="/mcp")
    def mcp_user(required_scope: str = "memory:read"):
        token = get_access_token()
        if token is None: raise ValueError("Bearer token erforderlich")
        if required_scope not in token.scopes: raise ValueError(f"MCP-Token benötigt den Bereich {required_scope}")
        return token.client_id
    @mcp.tool()
    def person_create_tool(first_name: str, last_name: str = "", birthday: str | None = None, notes: str = "") -> dict:
        owner_id = mcp_user("memory:write")
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
        owner_id = mcp_user("memory:write")
        with Session(engine) as db:
            user = db.get(User, owner_id); owned_person(db, person_id, user)
            row = Memory(owner_id=owner_id, person_id=person_id, title=title, content=content); db.add(row); db.commit(); db.refresh(row)
            return MemoryOut.model_validate(row).model_dump(mode="json")
    @mcp.tool()
    def memory_search_tool(query: str) -> dict:
        owner_id = mcp_user()
        with Session(engine) as db:
            user = db.get(User, owner_id); result = search(db, user, query)
            return {"people": [PersonOut.model_validate(x).model_dump(mode="json") for x in result["people"]], "memories": [MemoryOut.model_validate(x).model_dump(mode="json") for x in result["memories"]], "tasks": [TaskOut.model_validate(x).model_dump(mode="json") for x in result["tasks"]], "conversations": [ConversationOut.model_validate(x).model_dump(mode="json") for x in result["conversations"]], "loans": [LoanOut.model_validate(x).model_dump(mode="json") for x in result["loans"]], "gifts": [GiftOut.model_validate(x).model_dump(mode="json") for x in result["gifts"]]}

    @mcp.tool(name="person_get")
    def person_get_mcp(person_id: str) -> dict:
        owner_id = mcp_user()
        with Session(engine) as db:
            return PersonOut.model_validate(person_get(person_id, db, db.get(User, owner_id))).model_dump(mode="json")

    @mcp.tool(name="person_update")
    def person_update_mcp(person_id: str, first_name: str | None = None, last_name: str | None = None, nickname: str | None = None, birthday: str | None = None, email: str | None = None, phone: str | None = None, address: str | None = None, website: str | None = None, job_title: str | None = None, organization: str | None = None, notes: str | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        changes = {key: value for key, value in locals().copy().items() if key in PersonIn.model_fields and value is not None}
        with Session(engine) as db:
            person = owned_person(db, person_id, db.get(User, owner_id))
            for key, value in changes.items(): setattr(person, key, value)
            db.commit(); db.refresh(person)
            return PersonOut.model_validate(person).model_dump(mode="json")

    @mcp.tool(name="relationship_create")
    def relationship_create_mcp(source_person_id: str, target_person_id: str, relationship_type: str, inverse_relationship_type: str | None = None, source_memory_id: str | None = None, confirmed: bool = True) -> dict:
        owner_id = mcp_user("memory:write")
        with Session(engine) as db:
            row = relationship_add(RelationshipIn(source_person_id=source_person_id, target_person_id=target_person_id, relationship_type=relationship_type, inverse_relationship_type=inverse_relationship_type, source_memory_id=source_memory_id, confirmed=confirmed), db, db.get(User, owner_id))
            names = relationship_list(db, db.get(User, owner_id), source_person_id)
            match = next(item for item in names if item.id == row.id)
            return match.model_dump(mode="json")

    @mcp.tool(name="relationship_search")
    def relationship_search_mcp(person_id: str | None = None) -> list[dict]:
        owner_id = mcp_user()
        with Session(engine) as db:
            return [item.model_dump(mode="json") for item in relationship_list(db, db.get(User, owner_id), person_id)]

    @mcp.tool(name="memory_get")
    def memory_get_mcp(memory_id: str) -> dict:
        owner_id = mcp_user()
        with Session(engine) as db:
            row = db.scalar(select(Memory).where(Memory.id == memory_id, Memory.owner_id == owner_id))
            if row is None: raise ValueError("Erinnerung nicht gefunden")
            return MemoryOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="memory_update")
    def memory_update_mcp(memory_id: str, title: str | None = None, content: str | None = None, person_id: str | None = None, occurred_at: str | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        with Session(engine) as db:
            row = db.scalar(select(Memory).where(Memory.id == memory_id, Memory.owner_id == owner_id))
            if row is None: raise ValueError("Erinnerung nicht gefunden")
            if person_id is not None: owned_person(db, person_id, db.get(User, owner_id))
            parsed_occurred_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00")) if occurred_at is not None else None
            for key, value in (("title", title), ("content", content), ("person_id", person_id), ("occurred_at", parsed_occurred_at)):
                if value is not None: setattr(row, key, value)
            db.commit(); db.refresh(row)
            return MemoryOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="memory_delete")
    def memory_delete_mcp(memory_id: str, confirm: bool) -> dict:
        owner_id = mcp_user("memory:write")
        if not confirm: raise ValueError("Löschen erfordert confirm=true")
        with Session(engine) as db:
            row = db.scalar(select(Memory).where(Memory.id == memory_id, Memory.owner_id == owner_id))
            if row is None: raise ValueError("Erinnerung nicht gefunden")
            db.delete(row); db.commit()
            return {"deleted": True, "memory_id": memory_id}

    @mcp.tool(name="conversation_create")
    def conversation_create_mcp(title: str, original_note: str, participant_ids: list[str] | None = None, occurred_at: str | None = None, location: str = "", summary: str = "") -> dict:
        owner_id = mcp_user("memory:write")
        with Session(engine) as db:
            row = conversation_create(ConversationIn(title=title, original_note=original_note, participant_ids=participant_ids or [], occurred_at=occurred_at, location=location, summary=summary), db, db.get(User, owner_id))
            return row.model_dump(mode="json")

    @mcp.tool(name="conversation_search")
    def conversation_search_mcp(query: str = "", person_id: str | None = None) -> list[dict]:
        owner_id = mcp_user()
        with Session(engine) as db:
            return [row.model_dump(mode="json") for row in conversation_list(db, db.get(User, owner_id), person_id, query)]

    @mcp.tool(name="task_create")
    def task_create_mcp(title: str, description: str = "", person_id: str | None = None, due_at: str | None = None, priority: int = 2, repeat_interval_days: int | None = None, repeat_until: str | None = None) -> dict:
        from lifepilot.planner import task_create as create_task
        owner_id = mcp_user("memory:write")
        with Session(engine) as db:
            row = create_task(TaskIn(title=title, description=description, person_id=person_id, due_at=due_at, priority=priority, repeat_interval_days=repeat_interval_days, repeat_until=repeat_until), db, db.get(User, owner_id))
            return TaskOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="task_search")
    def task_search_mcp(status: str | None = None, person_id: str | None = None) -> list[dict]:
        from lifepilot.planner import task_list
        owner_id = mcp_user()
        with Session(engine) as db:
            rows = task_list(db, db.get(User, owner_id), status)
            if person_id is not None: rows = [row for row in rows if row.person_id == person_id]
            return [TaskOut.model_validate(row).model_dump(mode="json") for row in rows]

    @mcp.tool(name="task_complete")
    def task_complete_mcp(task_id: str) -> dict:
        from lifepilot.planner import task_complete
        owner_id = mcp_user("memory:write")
        with Session(engine) as db:
            row = task_complete(task_id, db, db.get(User, owner_id))
            return TaskOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="event_create")
    def event_create_mcp(title: str, starts_at: str, description: str = "", location: str = "", ends_at: str | None = None, participant_ids: list[str] | None = None, source_memory_id: str | None = None) -> dict:
        from lifepilot.planner import event_create
        owner_id = mcp_user("memory:write")
        with Session(engine) as db:
            row = event_create(EventIn(title=title, starts_at=starts_at, description=description, location=location, ends_at=ends_at, participant_ids=participant_ids or [], source_memory_id=source_memory_id), db, db.get(User, owner_id))
            return row.model_dump(mode="json")

    @mcp.tool(name="upcoming_events")
    def upcoming_events_mcp(from_at: str | None = None, to_at: str | None = None, person_id: str | None = None) -> list[dict]:
        from lifepilot.planner import event_list
        owner_id = mcp_user()
        with Session(engine) as db:
            start = datetime.fromisoformat(from_at.replace("Z", "+00:00")) if from_at else None
            end = datetime.fromisoformat(to_at.replace("Z", "+00:00")) if to_at else None
            rows = event_list(db, db.get(User, owner_id), start, end, person_id)
            return [row.model_dump(mode="json") for row in rows]

    @mcp.tool(name="loan_create")
    def loan_create_mcp(item_name: str, lender_person_id: str | None = None, borrower_person_id: str | None = None, due_at: str | None = None, condition_note: str = "", source_memory_id: str | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        with Session(engine) as db:
            row = loan_create(LoanIn(item_name=item_name, lender_person_id=lender_person_id, borrower_person_id=borrower_person_id, due_at=due_at, condition_note=condition_note, source_memory_id=source_memory_id), db, db.get(User, owner_id))
            return LoanOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="loan_search")
    def loan_search_mcp(open_only: bool = True, person_id: str | None = None) -> list[dict]:
        owner_id = mcp_user()
        with Session(engine) as db:
            rows = loan_list(db, db.get(User, owner_id), open_only, person_id)
            return [LoanOut.model_validate(row).model_dump(mode="json") for row in rows]

    @mcp.tool(name="loan_return")
    def loan_return_mcp(loan_id: str) -> dict:
        owner_id = mcp_user("memory:write")
        with Session(engine) as db:
            row = loan_return(loan_id, db, db.get(User, owner_id))
            return LoanOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="gift_create")
    def gift_create_mcp(person_id: str, title: str, note: str = "", occasion: str = "", budget: int | None = None, source_memory_id: str | None = None) -> dict:
        owner_id = mcp_user("memory:write")
        with Session(engine) as db:
            row = gift_create(GiftIn(person_id=person_id, title=title, note=note, occasion=occasion, budget=budget, source_memory_id=source_memory_id), db, db.get(User, owner_id))
            return GiftOut.model_validate(row).model_dump(mode="json")

    @mcp.tool(name="gift_search")
    def gift_search_mcp(person_id: str | None = None) -> list[dict]:
        owner_id = mcp_user()
        with Session(engine) as db:
            rows = gift_list(db, db.get(User, owner_id), person_id)
            return [GiftOut.model_validate(row).model_dump(mode="json") for row in rows]

    @mcp.tool(name="person_context")
    def person_context_mcp(person_id: str) -> dict:
        owner_id = mcp_user()
        with Session(engine) as db:
            data = person_briefing(person_id, db, db.get(User, owner_id))
            relationships = relationship_list(db, db.get(User, owner_id), person_id)
            return {"person": data["person"].model_dump(mode="json"), "memories": [row.model_dump(mode="json") for row in data["memories"]], "open_tasks": [row.model_dump(mode="json") for row in data["open_tasks"]], "relationships": [row.model_dump(mode="json") for row in relationships]}

    @mcp.tool(name="daily_briefing")
    def daily_briefing_mcp() -> dict:
        owner_id = mcp_user()
        with Session(engine) as db:
            result = daily_briefing(db, db.get(User, owner_id))
            return {"open_tasks": [row for row in result["open_tasks"]]}

    @mcp.tool(name="open_commitments")
    def open_commitments_mcp() -> dict:
        owner_id = mcp_user()
        with Session(engine) as db:
            tasks = db.scalars(select(Task).where(Task.owner_id == owner_id, Task.status == "open").order_by(Task.due_at)).all()
            loans = db.scalars(select(Loan).where(Loan.owner_id == owner_id, Loan.returned_at.is_(None)).order_by(Loan.due_at)).all()
            return {"tasks": [TaskOut.model_validate(row).model_dump(mode="json") for row in tasks], "loans": [LoanOut.model_validate(row).model_dump(mode="json") for row in loans]}
except ImportError:
    pass

def run_mcp():
    import uvicorn
    if "mcp" not in globals(): raise RuntimeError("MCP SDK is unavailable")
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=settings.mcp_port)
