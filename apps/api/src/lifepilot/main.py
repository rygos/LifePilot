from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import Depends, FastAPI, HTTPException, Query, Request, UploadFile, File
from starlette.responses import Response, FileResponse
from pathlib import Path
from uuid import uuid4
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.types import ASGIApp, Receive, Scope, Send
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import Text, delete, select, or_, text
from sqlalchemy.orm import Session
from lifepilot.config import settings
from lifepilot.db import Base, engine, get_db
from lifepilot.audit import AuditEventView
from lifepilot.models import AuditEvent, Conversation, ConversationParticipant, ConversationProject, Event, EventParticipant, Gift, Loan, Memory, MemoryProject, Person, PersonCallLog, PersonContactMethod, PersonLifeEvent, PersonNameHistory, Project, Relationship, Reminder, Task, User, UserPersonRelationship, Organization, PersonOrganization
from lifepilot.schemas import ContactMethodIn, ContactMethodOut, ConversationIn, ConversationOut, ConversationPatch, Credentials, EventIn, EventOut, GiftIn, GiftOut, LoanIn, LoanOut, MCPTokenRequest, MemoryIn, MemoryOut, PersonCallIn, PersonCallOut, PersonIn, PersonOut, PersonPatch, ProfileOut, ProfileUpdate, RelationshipIn, RelationshipOut, RelationshipWithPersonIn, RelationshipWithPersonOut, TaskIn, TaskOut, Token, UserPersonRelationshipIn, UserPersonRelationshipOut, OrganizationIn, OrganizationOut, MembershipIn, MembershipOut
from lifepilot.security import create_token, current_user, hash_password, verify_password
from lifepilot.services import ensure_self_person, owned_person, relationship_create, search, sync_account_from_self_person, sync_self_person_from_account
from lifepilot.scheduler import sync_contact_followup
from lifepilot.relationship_language import owner_relationship_label, refresh_relationship_labels
from lifepilot.planner import router as planner_router
from lifepilot.event_media import router as event_media_router
from lifepilot.attachment_routes import attachment_files_for_resource, remove_attachment_files, router as attachment_router
from lifepilot.capture_routes import router as capture_router
from lifepilot.project_routes import router as project_router
from lifepilot.approval_routes import router as approval_router
from lifepilot.embedding_jobs import enqueue_memory_embedding
from lifepilot.entity_embedding_jobs import delete_entity_embedding, enqueue_entity_embedding, enqueue_person_context_embeddings
from lifepilot.search_routes import router as search_router
from lifepilot.chat_routes import router as chat_router
from lifepilot.journal_routes import router as journal_router
from lifepilot.pet_routes import router as pet_router
from lifepilot.auth_routes import router as auth_router
from lifepilot.admin_routes import router as admin_router
from lifepilot.family_tree_routes import router as family_tree_router
from lifepilot.revisions import history, record_conversation_revision
from lifepilot.update_state import complete_pending_update
from lifepilot.commitment_routes import router as commitment_router, CommitmentOut, CheckpointOut, list_checkpoints, list_commitments
from lifepilot.models import Commitment
from lifepilot.next_action import router as next_action_router
from lifepilot.focus_routes import router as focus_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        if db.scalar(select(User).where(User.username == settings.life_pilot_bootstrap_username)) is None:
            first_user = db.scalar(select(User.id).limit(1)) is None
            db.add(User(username=settings.life_pilot_bootstrap_username, password_hash=hash_password(settings.life_pilot_bootstrap_password), role="admin" if first_user else "user"))
            db.flush()
        for owner in db.scalars(select(User)).all():
            ensure_self_person(db, owner)
        db.commit()
    complete_pending_update()
    yield

app = FastAPI(title="LifePilot", description="Dein persönliches digitales Gedächtnis", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.web_origin.split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(planner_router)
app.include_router(event_media_router)
app.include_router(attachment_router)
app.include_router(capture_router)
app.include_router(project_router)
app.include_router(approval_router)
app.include_router(search_router)
app.include_router(chat_router)
app.include_router(journal_router)
app.include_router(pet_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(family_tree_router)
app.include_router(commitment_router)
app.include_router(next_action_router)
app.include_router(focus_router)

@app.get("/health")
def health(): return {"status": "ok"}

@app.get("/ready")
def readiness():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Datenbank nicht erreichbar") from None
    if settings.redis_url:
        from redis import Redis
        try:
            with Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2) as redis:
                redis.ping()
        except Exception:
            raise HTTPException(status_code=503, detail="Redis nicht erreichbar") from None
    return {"status": "ready"}

@app.post("/api/auth/token", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == form.username, User.deleted_at.is_(None)))
    if user is None or not verify_password(form.password, user.password_hash): raise HTTPException(status_code=401, detail="Benutzername oder Passwort falsch")
    ensure_self_person(db, user); db.commit()
    return {"access_token": create_token(user.id, token_version=user.token_version)}

@app.post("/api/auth/login", response_model=Token)
def login_json(data: Credentials, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == data.username, User.deleted_at.is_(None)))
    if user is None or not verify_password(data.password, user.password_hash): raise HTTPException(status_code=401, detail="Benutzername oder Passwort falsch")
    ensure_self_person(db, user); db.commit()
    return {"access_token": create_token(user.id, token_version=user.token_version)}

@app.post("/api/auth/mcp-token", response_model=Token)
def mcp_token(data: MCPTokenRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == data.username, User.deleted_at.is_(None)))
    if user is None or not verify_password(data.password, user.password_hash): raise HTTPException(status_code=401, detail="Benutzername oder Passwort falsch")
    ensure_self_person(db, user); db.commit()
    scopes = ["memory:read"]
    if data.access == "read_write": scopes.append("memory:write")
    return {"access_token": create_token(user.id, scopes, token_use="mcp", token_version=user.token_version)}

@app.get("/api/auth/me")
def me(user: User = Depends(current_user)): return {"id": user.id, "username": user.username, "role": user.role}

@app.get("/api/profile", response_model=ProfileOut)
def profile_get(db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = ensure_self_person(db, user)
    db.commit()
    return ProfileOut.model_validate(user).model_copy(update={"self_person_id": person.id})

@app.patch("/api/profile", response_model=ProfileOut)
def profile_update(data: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    for key, value in data.model_dump(exclude_unset=True).items(): setattr(user, key, value)
    person = ensure_self_person(db, user)
    sync_self_person_from_account(person, user)
    db.commit(); db.refresh(user); return ProfileOut.model_validate(user).model_copy(update={"self_person_id": person.id})

@app.get("/api/people", response_model=list[PersonOut])
def people_list(db: Session = Depends(get_db), user: User = Depends(current_user), q: str = ""):
    ensure_self_person(db, user)
    db.commit()
    stmt = select(Person).where(Person.owner_id == user.id)
    if q:
        alias_ids = select(PersonNameHistory.person_id).where(PersonNameHistory.owner_id == user.id, PersonNameHistory.confirmed.is_(True), PersonNameHistory.name.ilike(f"%{q}%"))
        contact_ids = select(PersonContactMethod.person_id).where(PersonContactMethod.owner_id == user.id, or_(PersonContactMethod.value.ilike(f"%{q}%"), PersonContactMethod.label.ilike(f"%{q}%")))
        stmt = stmt.where(or_(Person.first_name.ilike(f"%{q}%"), Person.last_name.ilike(f"%{q}%"), Person.nickname.ilike(f"%{q}%"), Person.how_met.ilike(f"%{q}%"), Person.tags.cast(Text).ilike(f"%{q}%"), Person.id.in_(alias_ids), Person.id.in_(contact_ids)))
    return db.scalars(stmt.order_by(Person.is_self.desc(), Person.first_name, Person.last_name)).all()

@app.post("/api/people/{person_id}/photo", response_model=PersonOut)
async def person_photo_upload(person_id: str, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user)
    contents = await file.read(8 * 1024 * 1024 + 1)
    if len(contents) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Das Bild darf höchstens 8 MB groß sein")
    try:
        import io
        with Image.open(io.BytesIO(contents)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 40_000_000:
                raise HTTPException(status_code=415, detail="Bitte ein JPEG-, PNG- oder WebP-Bild unter 40 Megapixeln wählen")
            image = ImageOps.exif_transpose(image)
            image.thumbnail((2048, 2048))
            normalized = image.convert("RGB")
            output = io.BytesIO()
            normalized.save(output, format="JPEG", quality=88, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(status_code=415, detail="Die Datei ist kein gültiges Bild") from None
    photo_key = f"{uuid4().hex}.jpg"
    photo_dir = Path(settings.data_dir) / "people"
    photo_dir.mkdir(parents=True, exist_ok=True)
    (photo_dir / photo_key).write_bytes(output.getvalue())
    previous_key = person.photo_key
    person.photo_key = photo_key
    db.add(AuditEvent(owner_id=user.id, action="update", resource_type="people_photo", resource_id=person.id, source="web"))
    db.commit(); db.refresh(person)
    if previous_key:
        (photo_dir / previous_key).unlink(missing_ok=True)
    return person

@app.get("/api/people/{person_id}/photo")
def person_photo_get(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user)
    if not person.photo_key:
        raise HTTPException(status_code=404, detail="Für diese Person ist kein Profilbild gespeichert")
    photo_path = Path(settings.data_dir) / "people" / person.photo_key
    if not photo_path.is_file():
        raise HTTPException(status_code=404, detail="Das Profilbild wurde nicht gefunden")
    return FileResponse(photo_path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})

@app.delete("/api/people/{person_id}/photo", response_model=PersonOut)
def person_photo_delete(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user)
    old_key = person.photo_key
    person.photo_key = None
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="people_photo", resource_id=person.id, source="web"))
    db.commit(); db.refresh(person)
    if old_key:
        (Path(settings.data_dir) / "people" / old_key).unlink(missing_ok=True)
    return person

def organization_membership_out(db: Session, row: PersonOrganization, organization: Organization, person: Person) -> dict:
    return {"id": row.id, "person_id": person.id, "person_name": f"{person.first_name} {person.last_name}".strip(), "person_photo_key": person.photo_key, "person_birthday": person.birthday, "organization_id": organization.id, "organization_name": organization.name, "organization_type": organization.organization_type, "role": row.role, "valid_from": row.valid_from, "valid_until": row.valid_until}

@app.get("/api/organizations", response_model=list[OrganizationOut])
def organization_list(db: Session = Depends(get_db), user: User = Depends(current_user)):
    organizations = db.scalars(select(Organization).where(Organization.owner_id == user.id).order_by(Organization.name)).all()
    result = []
    for organization in organizations:
        memberships = db.execute(select(PersonOrganization, Person).join(Person, Person.id == PersonOrganization.person_id).where(PersonOrganization.owner_id == user.id, PersonOrganization.organization_id == organization.id).order_by(Person.first_name, Person.last_name)).all()
        result.append(OrganizationOut.model_validate(organization).model_copy(update={"members": [organization_membership_out(db, row, organization, person) for row, person in memberships]}))
    return result

@app.post("/api/organizations", response_model=OrganizationOut, status_code=201)
def organization_create(data: OrganizationIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Bitte einen Namen angeben")
    normalized = " ".join(name.casefold().split())
    existing = db.scalar(select(Organization).where(Organization.owner_id == user.id, Organization.normalized_name == normalized))
    if existing:
        raise HTTPException(status_code=409, detail="Diese Organisation ist bereits angelegt")
    row = Organization(owner_id=user.id, name=name, normalized_name=normalized, organization_type=data.organization_type, notes=data.notes)
    db.add(row); db.flush()
    db.add(AuditEvent(owner_id=user.id, action="create", resource_type="organizations", resource_id=row.id, source="web"))
    db.commit(); db.refresh(row)
    return row

@app.delete("/api/organizations/{organization_id}", status_code=204)
def organization_delete(organization_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    organization = db.scalar(select(Organization).where(Organization.id == organization_id, Organization.owner_id == user.id))
    if organization is None:
        raise HTTPException(status_code=404, detail="Verein oder Organisation nicht gefunden")
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="organizations", resource_id=organization.id, source="web"))
    db.delete(organization); db.commit()

@app.post("/api/people/{person_id}/organizations", response_model=MembershipOut, status_code=201)
def organization_membership_add(person_id: str, data: MembershipIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user)
    organization = db.scalar(select(Organization).where(Organization.id == data.organization_id, Organization.owner_id == user.id))
    if organization is None:
        raise HTTPException(status_code=404, detail="Verein oder Organisation nicht gefunden")
    if db.scalar(select(PersonOrganization).where(PersonOrganization.owner_id == user.id, PersonOrganization.person_id == person_id, PersonOrganization.organization_id == organization.id)):
        raise HTTPException(status_code=409, detail="Diese Mitgliedschaft ist bereits gespeichert")
    row = PersonOrganization(owner_id=user.id, person_id=person_id, organization_id=organization.id, role=data.role.strip(), valid_from=data.valid_from, valid_until=data.valid_until)
    db.add(row); db.flush()
    db.add(AuditEvent(owner_id=user.id, action="create", resource_type="person_organizations", resource_id=row.id, source="web"))
    db.commit()
    return organization_membership_out(db, row, organization, person)

@app.get("/api/people/{person_id}/organizations")
def person_organizations(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_person(db, person_id, user)
    rows = db.execute(select(PersonOrganization, Organization, Person).join(Organization, Organization.id == PersonOrganization.organization_id).join(Person, Person.id == PersonOrganization.person_id).where(PersonOrganization.owner_id == user.id, PersonOrganization.person_id == person_id).order_by(Organization.name)).all()
    return [organization_membership_out(db, membership, organization, person) for membership, organization, person in rows]

@app.delete("/api/organizations/{organization_id}/members/{person_id}", status_code=204)
def organization_membership_delete(organization_id: str, person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(PersonOrganization).where(PersonOrganization.owner_id == user.id, PersonOrganization.organization_id == organization_id, PersonOrganization.person_id == person_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Mitgliedschaft nicht gefunden")
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="person_organizations", resource_id=row.id, source="web"))
    db.delete(row); db.commit()

@app.post("/api/people", response_model=PersonOut, status_code=201)
def person_create(data: PersonIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = Person(owner_id=user.id, **data.model_dump(exclude_none=True)); db.add(person); db.commit(); db.refresh(person); return person

@app.get("/api/people/{person_id}/calls", response_model=list[PersonCallOut])
def person_call_list(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_person(db, person_id, user)
    return db.scalars(select(PersonCallLog).where(PersonCallLog.owner_id == user.id, PersonCallLog.person_id == person_id).order_by(PersonCallLog.occurred_at.desc(), PersonCallLog.created_at.desc())).all()

@app.post("/api/people/{person_id}/calls", response_model=PersonCallOut, status_code=201)
def person_call_create(person_id: str, data: PersonCallIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user)
    row = PersonCallLog(owner_id=user.id, person_id=person_id, **data.model_dump())
    db.add(row)
    if person.last_contact_at is None or data.occurred_at > person.last_contact_at:
        person.last_contact_at = data.occurred_at
    sync_contact_followup(db, person, user)
    db.flush()
    db.add(AuditEvent(owner_id=user.id, action="create", resource_type="person_call_logs", resource_id=row.id, source="web"))
    db.commit(); db.refresh(row)
    return row

@app.delete("/api/people/{person_id}/calls/{call_id}", status_code=204)
def person_call_delete(person_id: str, call_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user)
    row = db.scalar(select(PersonCallLog).where(PersonCallLog.id == call_id, PersonCallLog.owner_id == user.id, PersonCallLog.person_id == person_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Telefonat nicht gefunden")
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="person_call_logs", resource_id=row.id, source="web"))
    db.delete(row); db.flush()
    person.last_contact_at = db.scalar(select(PersonCallLog.occurred_at).where(PersonCallLog.owner_id == user.id, PersonCallLog.person_id == person_id).order_by(PersonCallLog.occurred_at.desc()).limit(1))
    sync_contact_followup(db, person, user)
    db.commit()

@app.get("/api/people/{person_id}", response_model=PersonOut)
def person_get(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return owned_person(db, person_id, user)

@app.patch("/api/people/{person_id}/favorite", response_model=PersonOut)
def person_favorite_toggle(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user)
    person.is_favorite = not person.is_favorite
    db.add(AuditEvent(owner_id=user.id, action="update", resource_type="people", resource_id=person.id, source="web"))
    db.commit(); db.refresh(person)
    return person

@app.get("/api/people/{person_id}/contact-methods", response_model=list[ContactMethodOut])
def person_contact_methods(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_person(db, person_id, user)
    return db.scalars(select(PersonContactMethod).where(PersonContactMethod.owner_id == user.id, PersonContactMethod.person_id == person_id).order_by(PersonContactMethod.method_type, PersonContactMethod.label, PersonContactMethod.created_at)).all()

@app.post("/api/people/{person_id}/contact-methods", response_model=ContactMethodOut, status_code=201)
def person_contact_method_create(person_id: str, data: ContactMethodIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_person(db, person_id, user)
    duplicate = db.scalar(select(PersonContactMethod.id).where(PersonContactMethod.owner_id == user.id, PersonContactMethod.person_id == person_id, PersonContactMethod.method_type == data.method_type, PersonContactMethod.label == data.label, PersonContactMethod.value == data.value))
    if duplicate:
        raise HTTPException(status_code=409, detail="Diese Kontaktmöglichkeit ist bereits gespeichert")
    row = PersonContactMethod(owner_id=user.id, person_id=person_id, **data.model_dump())
    db.add(row); db.flush()
    db.add(AuditEvent(owner_id=user.id, action="create", resource_type="person_contact_methods", resource_id=row.id, source="web"))
    db.commit(); db.refresh(row)
    return row

@app.patch("/api/contact-methods/{method_id}", response_model=ContactMethodOut)
def person_contact_method_update(method_id: str, data: ContactMethodIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(PersonContactMethod).where(PersonContactMethod.id == method_id, PersonContactMethod.owner_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Kontaktmöglichkeit nicht gefunden")
    duplicate = db.scalar(select(PersonContactMethod.id).where(PersonContactMethod.owner_id == user.id, PersonContactMethod.person_id == row.person_id, PersonContactMethod.method_type == data.method_type, PersonContactMethod.label == data.label, PersonContactMethod.value == data.value, PersonContactMethod.id != method_id))
    if duplicate:
        raise HTTPException(status_code=409, detail="Diese Kontaktmöglichkeit ist bereits gespeichert")
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    db.add(AuditEvent(owner_id=user.id, action="update", resource_type="person_contact_methods", resource_id=row.id, source="web"))
    db.commit(); db.refresh(row)
    return row

@app.delete("/api/contact-methods/{method_id}", status_code=204)
def person_contact_method_delete(method_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(PersonContactMethod).where(PersonContactMethod.id == method_id, PersonContactMethod.owner_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Kontaktmöglichkeit nicht gefunden")
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="person_contact_methods", resource_id=row.id, source="web"))
    db.delete(row); db.commit()

@app.get("/api/people/{person_id}/names")
def person_names(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_person(db, person_id, user)
    rows = db.scalars(select(PersonNameHistory).where(PersonNameHistory.owner_id == user.id, PersonNameHistory.person_id == person_id).order_by(PersonNameHistory.valid_until.desc().nullslast())).all()
    return [{"id": row.id, "name": row.name, "name_type": row.name_type, "valid_from": row.valid_from, "valid_until": row.valid_until, "confirmed": row.confirmed, "source_capture_id": row.source_capture_id} for row in rows]

@app.get("/api/people/{person_id}/life-events")
def person_life_events(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_person(db, person_id, user)
    rows = db.scalars(select(PersonLifeEvent).where(PersonLifeEvent.owner_id == user.id, PersonLifeEvent.person_id == person_id).order_by(PersonLifeEvent.occurred_at.desc().nullslast())).all()
    return [{"id": row.id, "title": row.title, "details": row.details, "occurred_at": row.occurred_at, "date_precision": row.date_precision, "confirmed": row.confirmed, "source_capture_id": row.source_capture_id} for row in rows]

@app.patch("/api/people/{person_id}", response_model=PersonOut)
def person_update(person_id: str, data: PersonPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user)
    previous_contact_interval = person.contact_interval_days
    updates = data.model_dump(exclude_unset=True, exclude={"gender"})
    for key, value in updates.items(): setattr(person, key, value)
    if "gender" in data.model_fields_set and data.gender is not None:
        person.gender = data.gender
        refresh_relationship_labels(db, user.id, person)
    if person.is_self:
        sync_account_from_self_person(person, user)
    sync_contact_followup(db, person, user, reactivate_muted=person.contact_interval_days is not None and person.contact_interval_days != previous_contact_interval)
    db.commit(); db.refresh(person)
    enqueue_person_context_embeddings(db, person.id, user.id)
    return person

@app.delete("/api/people/{person_id}", status_code=204)
def person_delete(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user)
    if person.is_self:
        raise HTTPException(status_code=409, detail="Das eigene Personenprofil kann nicht gelöscht werden")
    attachment_paths = attachment_files_for_resource(db, user.id, "person", person.id)
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="people", resource_id=person.id, source="web"))
    db.delete(person); db.commit()
    remove_attachment_files(attachment_paths)

@app.post("/api/people/{person_id}/owner-relationships", response_model=UserPersonRelationshipOut, status_code=201)
def owner_relationship_add(person_id: str, data: UserPersonRelationshipIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user)
    relationship_type = owner_relationship_label(data.relationship_type.strip(), person.gender)
    if not relationship_type:
        raise HTTPException(status_code=422, detail="Bitte eine Beziehung angeben")
    if data.valid_until is None:
        row = db.scalar(select(UserPersonRelationship).where(UserPersonRelationship.owner_id == user.id, UserPersonRelationship.person_id == person_id, UserPersonRelationship.relationship_type == relationship_type, UserPersonRelationship.valid_until.is_(None)))
        if row is not None:
            return row
    row = UserPersonRelationship(owner_id=user.id, person_id=person_id, relationship_type=relationship_type, valid_from=data.valid_from, valid_until=data.valid_until, confirmed=True)
    db.add(row)
    db.flush()
    db.add(AuditEvent(owner_id=user.id, action="create", resource_type="user_person_relationships", resource_id=row.id, source="web"))
    db.commit()
    db.refresh(row)
    return row

@app.delete("/api/owner-relationships/{relationship_id}", status_code=204)
def owner_relationship_delete(relationship_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(UserPersonRelationship).where(UserPersonRelationship.id == relationship_id, UserPersonRelationship.owner_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Beziehung nicht gefunden")
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="user_person_relationships", resource_id=row.id, source="web"))
    db.delete(row)
    db.commit()

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

@app.post("/api/relationships/with-new-person", response_model=RelationshipWithPersonOut, status_code=201)
def relationship_add_with_new_person(data: RelationshipWithPersonIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    source = owned_person(db, data.source_person_id, user)
    person = Person(owner_id=user.id, **data.new_person.model_dump(exclude_none=True))
    db.add(person); db.flush()
    relationship = relationship_create(db, user, source.id, person.id, data.relationship_type, None, True, commit=False)
    db.add(AuditEvent(owner_id=user.id, action="create", resource_type="people", resource_id=person.id, source="web"))
    db.add(AuditEvent(owner_id=user.id, action="create", resource_type="relationships", resource_id=relationship.id, source="web"))
    db.commit(); db.refresh(person); db.refresh(relationship)
    enqueue_entity_embedding("relationship", relationship.id, user.id)
    relationship_out = RelationshipOut(id=relationship.id, source_person_id=source.id, source_person_name=f"{source.first_name} {source.last_name}".strip(), target_person_id=person.id, target_person_name=f"{person.first_name} {person.last_name}".strip(), relationship_type=relationship.relationship_type, inverse_relationship_type=relationship.inverse_relationship_type, confirmed=relationship.confirmed, source_memory_id=relationship.source_memory_id)
    return RelationshipWithPersonOut(person=PersonOut.model_validate(person), relationship=relationship_out)

@app.delete("/api/relationships/{relationship_id}", status_code=204)
def relationship_delete(relationship_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(Relationship).where(Relationship.id == relationship_id, Relationship.owner_id == user.id))
    if row is None: raise HTTPException(status_code=404, detail="Beziehung nicht gefunden")
    delete_entity_embedding(db, "relationship", row.id, user.id)
    db.delete(row); db.commit()

@app.delete("/api/memories/{memory_id}", status_code=204)
def memory_delete(memory_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(Memory).where(Memory.id == memory_id, Memory.owner_id == user.id))
    if row is None: raise HTTPException(status_code=404, detail="Erinnerung nicht gefunden")
    attachment_paths = attachment_files_for_resource(db, user.id, "memory", row.id)
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="memories", resource_id=row.id, source="web"))
    db.delete(row); db.commit()
    remove_attachment_files(attachment_paths)

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
    if q:
        alias_ids = select(PersonNameHistory.person_id).where(PersonNameHistory.owner_id == user.id, PersonNameHistory.confirmed.is_(True), PersonNameHistory.name.ilike(f"%{q}%"))
        memory_ids = select(MemoryProject.memory_id).where(MemoryProject.owner_id == user.id, MemoryProject.project_id.in_(select(Project.id).where(Project.owner_id == user.id, or_(Project.name.ilike(f"%{q}%"), Project.description.ilike(f"%{q}%")))))
        stmt = stmt.where(or_(Memory.title.ilike(f"%{q}%"), Memory.content.ilike(f"%{q}%"), Memory.person_id.in_(alias_ids), Memory.id.in_(memory_ids)))
    return db.scalars(stmt.order_by(Memory.created_at.desc())).all()

@app.get("/api/search")
def memory_search(q: str = Query(min_length=1), db: Session = Depends(get_db), user: User = Depends(current_user)):
    return search(db, user, q)

@app.post("/api/conversations", response_model=ConversationOut, status_code=201)
def conversation_create(data: ConversationIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    participant_ids = list(dict.fromkeys(data.participant_ids))
    project_ids = list(dict.fromkeys(data.project_ids))
    if participant_ids:
        people = db.scalars(select(Person).where(Person.owner_id == user.id, Person.id.in_(participant_ids))).all()
        if len(people) != len(participant_ids): raise HTTPException(status_code=404, detail="Mindestens eine beteiligte Person wurde nicht gefunden")
    if project_ids:
        projects = db.scalars(select(Project).where(Project.owner_id == user.id, Project.id.in_(project_ids))).all()
        if len(projects) != len(project_ids): raise HTTPException(status_code=404, detail="Mindestens ein verknüpftes Projekt wurde nicht gefunden")
    conversation = Conversation(owner_id=user.id, title=data.title, original_note=data.original_note, summary=data.summary, location=data.location, occurred_at=data.occurred_at)
    db.add(conversation); db.flush()
    db.add_all(ConversationParticipant(conversation_id=conversation.id, person_id=person_id, owner_id=user.id) for person_id in participant_ids)
    db.add_all(ConversationProject(conversation_id=conversation.id, project_id=project_id, owner_id=user.id) for project_id in project_ids)
    record_conversation_revision(db, conversation, "created", "rest")
    db.commit(); db.refresh(conversation)
    enqueue_entity_embedding("conversation", conversation.id, user.id)
    return ConversationOut(id=conversation.id, title=conversation.title, original_note=conversation.original_note, summary=conversation.summary, location=conversation.location, occurred_at=conversation.occurred_at, created_at=conversation.created_at, participant_ids=participant_ids, project_ids=project_ids)

@app.get("/api/conversations", response_model=list[ConversationOut])
def conversation_list(db: Session = Depends(get_db), user: User = Depends(current_user), person_id: str | None = None, q: str = ""):
    stmt = select(Conversation).where(Conversation.owner_id == user.id)
    if person_id: stmt = stmt.join(ConversationParticipant).where(ConversationParticipant.person_id == person_id, ConversationParticipant.owner_id == user.id)
    if q: stmt = stmt.where(or_(Conversation.title.ilike(f"%{q}%"), Conversation.original_note.ilike(f"%{q}%"), Conversation.summary.ilike(f"%{q}%")))
    rows = db.scalars(stmt.order_by(Conversation.occurred_at.desc().nullslast(), Conversation.created_at.desc())).all()
    return [ConversationOut(id=row.id, title=row.title, original_note=row.original_note, summary=row.summary, location=row.location, occurred_at=row.occurred_at, created_at=row.created_at, participant_ids=list(db.scalars(select(ConversationParticipant.person_id).where(ConversationParticipant.conversation_id == row.id, ConversationParticipant.owner_id == user.id)).all()), project_ids=list(db.scalars(select(ConversationProject.project_id).where(ConversationProject.conversation_id == row.id, ConversationProject.owner_id == user.id)).all())) for row in rows]

@app.get("/api/conversations/{conversation_id}/history")
def conversation_history(conversation_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return history(db, user.id, "conversation", conversation_id)

@app.patch("/api/conversations/{conversation_id}", response_model=ConversationOut)
def conversation_update(conversation_id: str, data: ConversationPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.owner_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Gespräch nicht gefunden")
    changes = data.model_dump(exclude_unset=True)
    participant_ids = changes.pop("participant_ids", None)
    project_ids = changes.pop("project_ids", None)
    if participant_ids is not None:
        ids = set(participant_ids)
        valid = set(db.scalars(select(Person.id).where(Person.owner_id == user.id, Person.id.in_(ids))).all()) if ids else set()
        if ids != valid:
            raise HTTPException(status_code=404, detail="Mindestens eine beteiligte Person wurde nicht gefunden")
        db.execute(delete(ConversationParticipant).where(ConversationParticipant.conversation_id == row.id, ConversationParticipant.owner_id == user.id))
        db.add_all(ConversationParticipant(conversation_id=row.id, person_id=person_id, owner_id=user.id) for person_id in ids)
    if project_ids is not None:
        ids = set(project_ids)
        valid = set(db.scalars(select(Project.id).where(Project.owner_id == user.id, Project.id.in_(ids))).all()) if ids else set()
        if ids != valid:
            raise HTTPException(status_code=404, detail="Mindestens ein verknüpftes Projekt wurde nicht gefunden")
        db.execute(delete(ConversationProject).where(ConversationProject.conversation_id == row.id, ConversationProject.owner_id == user.id))
        db.add_all(ConversationProject(conversation_id=row.id, project_id=project_id, owner_id=user.id) for project_id in ids)
    for key, value in changes.items():
        setattr(row, key, value)
    record_conversation_revision(db, row, "updated", "rest")
    db.commit()
    db.refresh(row)
    enqueue_entity_embedding("conversation", row.id, user.id)
    return ConversationOut(id=row.id, title=row.title, original_note=row.original_note, summary=row.summary, location=row.location, occurred_at=row.occurred_at, created_at=row.created_at, participant_ids=list(db.scalars(select(ConversationParticipant.person_id).where(ConversationParticipant.conversation_id == row.id, ConversationParticipant.owner_id == user.id)).all()), project_ids=list(db.scalars(select(ConversationProject.project_id).where(ConversationProject.conversation_id == row.id, ConversationProject.owner_id == user.id)).all()))

@app.delete("/api/conversations/{conversation_id}", status_code=204)
def conversation_delete(conversation_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.owner_id == user.id))
    if row is None: raise HTTPException(status_code=404, detail="Gespräch nicht gefunden")
    delete_entity_embedding(db, "conversation", row.id, user.id)
    attachment_paths = attachment_files_for_resource(db, user.id, "conversation", row.id)
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="conversations", resource_id=row.id, source="web"))
    db.delete(row); db.commit()
    remove_attachment_files(attachment_paths)

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

@app.delete("/api/loans/{loan_id}", status_code=204)
def loan_delete(loan_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(Loan).where(Loan.id == loan_id, Loan.owner_id == user.id))
    if row is None: raise HTTPException(status_code=404, detail="Leihgabe nicht gefunden")
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="loans", resource_id=row.id, source="web"))
    db.delete(row); db.commit()

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

@app.delete("/api/gifts/{gift_id}", status_code=204)
def gift_delete(gift_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(Gift).where(Gift.id == gift_id, Gift.owner_id == user.id))
    if row is None: raise HTTPException(status_code=404, detail="Geschenkidee nicht gefunden")
    db.add(AuditEvent(owner_id=user.id, action="delete", resource_type="gifts", resource_id=row.id, source="web"))
    db.delete(row); db.commit()

@app.get("/api/briefing/daily")
def daily_briefing(db: Session = Depends(get_db), user: User = Depends(current_user)):
    local_now = datetime.now(timezone.utc).astimezone(ZoneInfo(user.timezone_name))
    start = datetime.combine(local_now.date(), time.min, tzinfo=local_now.tzinfo).astimezone(timezone.utc)
    end = datetime.combine(local_now.date() + timedelta(days=1), time.min, tzinfo=local_now.tzinfo).astimezone(timezone.utc)
    horizon = datetime.combine(local_now.date() + timedelta(days=7), time.min, tzinfo=local_now.tzinfo).astimezone(timezone.utc)
    if db.bind and db.bind.dialect.name == "sqlite":
        start, end, horizon = start.replace(tzinfo=None), end.replace(tzinfo=None), horizon.replace(tzinfo=None)
    tasks = db.scalars(select(Task).where(Task.owner_id == user.id, Task.status == "open", or_(Task.due_at.is_(None), Task.due_at < horizon)).order_by(Task.due_at.is_(None), Task.due_at).limit(20)).all()
    events = db.scalars(select(Event).where(Event.owner_id == user.id, Event.starts_at >= start, Event.starts_at < end).order_by(Event.starts_at).limit(20)).all()
    reminders = db.scalars(select(Reminder).where(Reminder.owner_id == user.id, Reminder.state == "scheduled", Reminder.due_at < horizon).order_by(Reminder.due_at).limit(20)).all()
    return {
        "date": local_now.date().isoformat(),
        "timezone": user.timezone_name,
        "open_commitments": [CommitmentOut.model_validate(row).model_dump(mode="json") for row in list_commitments(db, user.id, limit=20)],
        "active_checkpoints": [CheckpointOut.model_validate(row).model_dump(mode="json") for row in list_checkpoints(db, user.id, limit=5)],
        "open_tasks": [TaskOut.model_validate(task).model_dump(mode="json") for task in tasks],
        "today_events": [EventOut(id=event.id, record_type=event.record_type, title=event.title, description=event.description, location=event.location, location_address=event.location_address, starts_at=event.starts_at, ends_at=event.ends_at, source_memory_id=event.source_memory_id, participant_ids=list(db.scalars(select(EventParticipant.person_id).where(EventParticipant.event_id == event.id, EventParticipant.owner_id == user.id)).all())).model_dump(mode="json") for event in events],
        "upcoming_reminders": [{"id": reminder.id, "title": reminder.title, "due_at": reminder.due_at, "state": reminder.state, "source_type": "task" if reminder.task_id else "event" if reminder.event_id else "contact" if reminder.contact_person_id else "reminder", "source_id": reminder.task_id or reminder.event_id or reminder.contact_person_id or reminder.id} for reminder in reminders],
    }

@app.get("/api/audit", response_model=list[AuditEventView])
def audit_list(db: Session = Depends(get_db), user: User = Depends(current_user), limit: int = Query(default=50, ge=1, le=200)) -> list[AuditEvent]:
    return list(db.scalars(select(AuditEvent).where(AuditEvent.owner_id == user.id).order_by(AuditEvent.created_at.desc()).limit(limit)).all())

@app.get("/api/briefing/person/{person_id}")
def person_briefing(person_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    person = owned_person(db, person_id, user)
    memories = db.scalars(select(Memory).where(Memory.owner_id == user.id, Memory.person_id == person_id).order_by(Memory.occurred_at.desc().nullslast(), Memory.created_at.desc()).limit(10)).all()
    conversations = db.scalars(select(Conversation).join(ConversationParticipant, ConversationParticipant.conversation_id == Conversation.id).where(Conversation.owner_id == user.id, ConversationParticipant.owner_id == user.id, ConversationParticipant.person_id == person_id).order_by(Conversation.occurred_at.desc().nullslast(), Conversation.created_at.desc()).limit(10)).all()
    tasks = db.scalars(select(Task).where(Task.owner_id == user.id, Task.person_id == person_id, Task.status == "open").order_by(Task.due_at.is_(None), Task.due_at)).all()
    links = db.scalars(select(Relationship).where(Relationship.owner_id == user.id, or_(Relationship.source_person_id == person_id, Relationship.target_person_id == person_id))).all()
    loans = db.scalars(select(Loan).where(Loan.owner_id == user.id, Loan.returned_at.is_(None), or_(Loan.lender_person_id == person_id, Loan.borrower_person_id == person_id)).order_by(Loan.due_at.is_(None), Loan.due_at)).all()
    gifts = db.scalars(select(Gift).where(Gift.owner_id == user.id, Gift.person_id == person_id, Gift.status.in_(["idea", "planned"])).order_by(Gift.created_at.desc()).limit(10)).all()
    life_events = db.scalars(select(PersonLifeEvent).where(PersonLifeEvent.owner_id == user.id, PersonLifeEvent.person_id == person_id, PersonLifeEvent.confirmed.is_(True)).order_by(PersonLifeEvent.occurred_at.desc().nullslast()).limit(20)).all()
    owner_relationships = db.scalars(select(UserPersonRelationship).where(UserPersonRelationship.owner_id == user.id, UserPersonRelationship.person_id == person_id, UserPersonRelationship.confirmed.is_(True)).order_by(UserPersonRelationship.valid_from.desc().nullslast())).all()
    participated_events = db.scalars(select(Event).join(EventParticipant, EventParticipant.event_id == Event.id).where(Event.owner_id == user.id, EventParticipant.owner_id == user.id, EventParticipant.person_id == person_id).order_by(Event.starts_at.desc()).limit(50)).all()
    now = datetime.now(timezone.utc)
    upcoming_events = db.scalars(select(Event).join(EventParticipant, EventParticipant.event_id == Event.id).where(Event.owner_id == user.id, EventParticipant.owner_id == user.id, EventParticipant.person_id == person_id, Event.starts_at >= now).order_by(Event.starts_at).limit(10)).all()
    return {
        "person": PersonOut.model_validate(person).model_dump(mode="json"),
        "open_commitments": [CommitmentOut.model_validate(row).model_dump(mode="json") for row in db.scalars(select(Commitment).where(Commitment.owner_id == user.id, Commitment.person_id == person_id, Commitment.status == "open").order_by(Commitment.due_at.is_(None), Commitment.due_at, Commitment.id).limit(20))],
        "owner_relationships": [{"id": row.id, "relationship_type": row.relationship_type, "valid_from": row.valid_from, "valid_until": row.valid_until, "source_capture_id": row.source_capture_id, "confirmed": row.confirmed} for row in owner_relationships],
        "former_names": [{"id": row.id, "name": row.name, "valid_from": row.valid_from, "valid_until": row.valid_until, "confirmed": row.confirmed, "source_capture_id": row.source_capture_id} for row in db.scalars(select(PersonNameHistory).where(PersonNameHistory.owner_id == user.id, PersonNameHistory.person_id == person_id, PersonNameHistory.confirmed.is_(True)).order_by(PersonNameHistory.valid_until.desc().nullslast())).all()],
        "life_events": [{"id": row.id, "title": row.title, "details": row.details, "occurred_at": row.occurred_at, "date_precision": row.date_precision, "confirmed": row.confirmed, "source_capture_id": row.source_capture_id} for row in life_events],
        "memories": [MemoryOut.model_validate(memory).model_dump(mode="json") for memory in memories],
        "conversations": [ConversationOut(id=row.id, title=row.title, original_note=row.original_note, summary=row.summary, location=row.location, occurred_at=row.occurred_at, created_at=row.created_at, participant_ids=list(db.scalars(select(ConversationParticipant.person_id).where(ConversationParticipant.conversation_id == row.id, ConversationParticipant.owner_id == user.id)).all()), project_ids=list(db.scalars(select(ConversationProject.project_id).where(ConversationProject.conversation_id == row.id, ConversationProject.owner_id == user.id)).all())).model_dump(mode="json") for row in conversations],
        "open_tasks": [TaskOut.model_validate(task).model_dump(mode="json") for task in tasks],
        "relationships": [{"id": row.id, "source_person_id": row.source_person_id, "target_person_id": row.target_person_id, "relationship_type": row.relationship_type, "inverse_relationship_type": row.inverse_relationship_type, "valid_from": row.valid_from, "valid_until": row.valid_until, "confirmed": row.confirmed, "source_memory_id": row.source_memory_id} for row in links],
        "open_loans": [LoanOut.model_validate(loan).model_dump(mode="json") for loan in loans],
        "gift_ideas": [GiftOut.model_validate(gift).model_dump(mode="json") for gift in gifts],
        "participated_events": [EventOut(id=event.id, record_type=event.record_type, title=event.title, description=event.description, location=event.location, location_address=event.location_address, starts_at=event.starts_at, ends_at=event.ends_at, source_memory_id=event.source_memory_id, participant_ids=list(db.scalars(select(EventParticipant.person_id).where(EventParticipant.event_id == event.id, EventParticipant.owner_id == user.id)).all())).model_dump(mode="json") for event in participated_events],
        "upcoming_events": [EventOut(id=event.id, record_type=event.record_type, title=event.title, description=event.description, location=event.location, location_address=event.location_address, starts_at=event.starts_at, ends_at=event.ends_at, source_memory_id=event.source_memory_id, participant_ids=[person_id]).model_dump(mode="json") for event in upcoming_events],
    }

try:
    from lifepilot.mcp_tools import mcp
except ImportError:
    mcp = None

def run_mcp():
    import uvicorn
    if mcp is None: raise RuntimeError("MCP SDK ist nicht verfügbar")
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=settings.mcp_port)
