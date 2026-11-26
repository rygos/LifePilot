from datetime import date, datetime, time, timezone
from uuid import uuid4
from sqlalchemy import JSON, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from lifepilot.db import Base
from lifepilot.entity_types import EntityType

def now(): return datetime.now(timezone.utc)
def new_id(): return str(uuid4())

class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user", server_default="user", nullable=False)
    full_name: Mapped[str] = mapped_column(String(240), default="")
    nickname: Mapped[str | None] = mapped_column(String(120), nullable=True)
    birthday: Mapped[str | None] = mapped_column(String(10), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    address: Mapped[str] = mapped_column(Text, default="")
    timezone_name: Mapped[str] = mapped_column(String(64), default="Europe/Berlin", server_default="Europe/Berlin")
    quiet_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

class Person(Base):
    __tablename__ = "people"
    __table_args__ = (
        Index("uq_people_one_self_profile_per_owner", "owner_id", unique=True, postgresql_where=text("is_self = true"), sqlite_where=text("is_self = true")),
        CheckConstraint("birthday_precision IN ('exact', 'month_day', 'approximate', 'unknown')", name="ck_people_birthday_precision"),
        CheckConstraint("contact_interval_days IS NULL OR contact_interval_days BETWEEN 1 AND 365", name="ck_people_contact_interval_days"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    first_name: Mapped[str] = mapped_column(String(120))
    last_name: Mapped[str] = mapped_column(String(120), default="")
    nickname: Mapped[str | None] = mapped_column(String(120), nullable=True)
    birthday: Mapped[str | None] = mapped_column(String(10), nullable=True)
    birthday_precision: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown", nullable=False)
    birthday_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    birthday_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    birthday_approximate_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contact_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gender: Mapped[str] = mapped_column(String(20), default="unspecified", server_default="unspecified", nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    address: Mapped[str] = mapped_column(Text, default="")
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(200), nullable=True)
    how_met: Mapped[str] = mapped_column(Text, default="", server_default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]", nullable=False)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    photo_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_self: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    contact_methods: Mapped[list["PersonContactMethod"]] = relationship(back_populates="person", cascade="all, delete-orphan", lazy="selectin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class PersonContactMethod(Base):
    __tablename__ = "person_contact_methods"
    __table_args__ = (UniqueConstraint("owner_id", "person_id", "method_type", "label", "value", name="uq_person_contact_method_value"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    method_type: Mapped[str] = mapped_column(String(24))
    label: Mapped[str] = mapped_column(String(80), default="")
    value: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    person: Mapped[Person] = relationship(back_populates="contact_methods")

class PersonCallLog(Base):
    __tablename__ = "person_call_logs"
    __table_args__ = (Index("ix_person_call_logs_person_occurred", "owner_id", "person_id", "occurred_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("owner_id", "normalized_name", name="uq_organizations_owner_name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200))
    organization_type: Mapped[str] = mapped_column(String(40), default="club")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class PersonOrganization(Base):
    __tablename__ = "person_organizations"
    __table_args__ = (UniqueConstraint("owner_id", "person_id", "organization_id", name="uq_person_organization_membership"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(160), default="")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class PersonNameHistory(Base):
    __tablename__ = "person_name_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    name_type: Mapped[str] = mapped_column(String(40), default="former")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_capture_id: Mapped[str | None] = mapped_column(ForeignKey("captures.id", ondelete="SET NULL"), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class PersonLifeEvent(Base):
    __tablename__ = "person_life_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    details: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_precision: Mapped[str] = mapped_column(String(20), default="unknown")
    source_capture_id: Mapped[str | None] = mapped_column(ForeignKey("captures.id", ondelete="SET NULL"), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Memory(Base):
    __tablename__ = "memories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(40), default="manual")
    source_capture_id: Mapped[str | None] = mapped_column(ForeignKey("captures.id", ondelete="SET NULL"), nullable=True, index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class JournalEntry(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        CheckConstraint("mood IS NULL OR mood IN ('freudig', 'ruhig', 'neutral', 'traurig', 'gestresst', 'dankbar', 'energiegeladen')", name="ck_journal_entries_mood"),
        Index("ix_journal_entries_owner_date", "owner_id", "entry_date"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    title: Mapped[str] = mapped_column(String(240), default="")
    content: Mapped[str] = mapped_column(Text)
    mood: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class JournalEntryPerson(Base):
    __tablename__ = "journal_entry_people"
    entry_id: Mapped[str] = mapped_column(ForeignKey("journal_entries.id", ondelete="CASCADE"), primary_key=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

class JournalEntryProject(Base):
    __tablename__ = "journal_entry_projects"
    entry_id: Mapped[str] = mapped_column(ForeignKey("journal_entries.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

class JournalEntryEvent(Base):
    __tablename__ = "journal_entry_events"
    entry_id: Mapped[str] = mapped_column(ForeignKey("journal_entries.id", ondelete="CASCADE"), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

class Pet(Base):
    __tablename__ = "pets"
    __table_args__ = (
        CheckConstraint("sex IN ('female', 'male', 'unknown')", name="ck_pets_sex"),
        Index("ix_pets_owner_name", "owner_id", "name"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    species: Mapped[str] = mapped_column(String(80))
    breed: Mapped[str] = mapped_column(String(120), default="")
    sex: Mapped[str] = mapped_column(String(16), default="unknown")
    birthday: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_neutered: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class PetPerson(Base):
    __tablename__ = "pet_people"
    __table_args__ = (CheckConstraint("relationship_type IN ('owner', 'caretaker', 'lives_with')", name="ck_pet_people_relationship_type"),)
    pet_id: Mapped[str] = mapped_column(ForeignKey("pets.id", ondelete="CASCADE"), primary_key=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    relationship_type: Mapped[str] = mapped_column(String(20), default="owner")

class PetEvent(Base):
    __tablename__ = "pet_events"
    pet_id: Mapped[str] = mapped_column(ForeignKey("pets.id", ondelete="CASCADE"), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

class MemoryEmbedding(Base):
    __tablename__ = "memory_embeddings"
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(160))
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(Vector(768))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class EntityEmbedding(Base):
    __tablename__ = "entity_embeddings"
    __table_args__ = (
        CheckConstraint("(entity_type = 'conversation' AND conversation_id = entity_id AND task_id IS NULL AND relationship_id IS NULL AND project_id IS NULL) OR (entity_type = 'task' AND task_id = entity_id AND conversation_id IS NULL AND relationship_id IS NULL AND project_id IS NULL) OR (entity_type = 'relationship' AND relationship_id = entity_id AND conversation_id IS NULL AND task_id IS NULL AND project_id IS NULL) OR (entity_type = 'project' AND project_id = entity_id AND conversation_id IS NULL AND task_id IS NULL AND relationship_id IS NULL)", name="ck_entity_embeddings_single_target"),
        UniqueConstraint("conversation_id", name="uq_entity_embeddings_conversation"),
        UniqueConstraint("task_id", name="uq_entity_embeddings_task"),
        UniqueConstraint("relationship_id", name="uq_entity_embeddings_relationship"),
        UniqueConstraint("project_id", name="uq_entity_embeddings_project"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[EntityType] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(36))
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True)
    relationship_id: Mapped[str | None] = mapped_column(ForeignKey("relationships.id", ondelete="CASCADE"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    model: Mapped[str] = mapped_column(String(160))
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(Vector(768))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class Task(Base):
    __tablename__ = "tasks"
    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mental_effort: Mapped[str | None] = mapped_column(String(12), nullable=True)
    start_friction: Mapped[str | None] = mapped_column(String(12), nullable=True)
    work_context: Mapped[str | None] = mapped_column(String(20), nullable=True)
    next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    repeat_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repeat_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=2)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Relationship(Base):
    __tablename__ = "relationships"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    target_person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    relationship_type: Mapped[str] = mapped_column(String(100))
    inverse_relationship_type: Mapped[str] = mapped_column(String(100), default="Beziehung zu")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_memory_id: Mapped[str | None] = mapped_column(ForeignKey("memories.id", ondelete="SET NULL"), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class UserPersonRelationship(Base):
    __tablename__ = "user_person_relationships"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    relationship_type: Mapped[str] = mapped_column(String(100))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_capture_id: Mapped[str | None] = mapped_column(ForeignKey("captures.id", ondelete="SET NULL"), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    original_note: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(240), default="")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ConversationParticipant(Base):
    __tablename__ = "conversation_participants"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

class Loan(Base):
    __tablename__ = "loans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_name: Mapped[str] = mapped_column(String(240))
    lender_person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), nullable=True)
    borrower_person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), nullable=True)
    lent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    condition_note: Mapped[str] = mapped_column(Text, default="")
    source_memory_id: Mapped[str | None] = mapped_column(ForeignKey("memories.id", ondelete="SET NULL"), nullable=True)

class Gift(Base):
    __tablename__ = "gifts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    note: Mapped[str] = mapped_column(Text, default="")
    occasion: Mapped[str] = mapped_column(String(120), default="")
    budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="idea", index=True)
    source_memory_id: Mapped[str | None] = mapped_column(ForeignKey("memories.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    record_type: Mapped[str] = mapped_column(String(20), default="appointment", index=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(240), default="")
    location_address: Mapped[str] = mapped_column(String(500), default="")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_memory_id: Mapped[str | None] = mapped_column(ForeignKey("memories.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class EventParticipant(Base):
    __tablename__ = "event_participants"
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

class EventPhoto(Base):
    __tablename__ = "event_photos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    file_key: Mapped[str] = mapped_column(String(80))
    caption: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint("resource_type IN ('person', 'memory', 'conversation', 'event', 'project')", name="ck_attachments_resource_type"),
        Index("ix_attachments_owner_resource", "owner_id", "resource_type", "resource_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resource_type: Mapped[str] = mapped_column(String(24))
    resource_id: Mapped[str] = mapped_column(String(36))
    storage_key: Mapped[str] = mapped_column(String(120), unique=True)
    file_name: Mapped[str] = mapped_column(String(240))
    content_type: Mapped[str] = mapped_column(String(160))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (UniqueConstraint("task_id"), UniqueConstraint("event_id"), UniqueConstraint("birthday_person_id", "birthday_year", name="uq_reminders_birthday_person_year"), UniqueConstraint("contact_person_id", name="uq_reminders_contact_person"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=True, index=True)
    birthday_person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), nullable=True, index=True)
    birthday_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contact_person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), nullable=True, index=True)
    state: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(20))
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20), default="mcp")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

class ResourceRevision(Base):
    __tablename__ = "resource_revisions"
    __table_args__ = (UniqueConstraint("owner_id", "resource_type", "resource_id", "revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resource_type: Mapped[str] = mapped_column(String(40), index=True)
    resource_id: Mapped[str] = mapped_column(String(36), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20), default="application")
    snapshot_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

class Capture(Base):
    __tablename__ = "captures"
    __table_args__ = (UniqueConstraint("owner_id", "client_request_id", name="uq_capture_client_request"),)
    client_request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_capture_id: Mapped[str | None] = mapped_column(ForeignKey("captures.id", ondelete="SET NULL"), nullable=True, index=True)
    original_text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="capture", server_default="capture", index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    suggestions_json: Mapped[str] = mapped_column(Text, default="[]")
    processing_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class ConversationProject(Base):
    __tablename__ = "conversation_projects"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

class MemoryProject(Base):
    __tablename__ = "memory_projects"
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    operation: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(36))
    resource_label: Mapped[str] = mapped_column(String(240), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Commitment(Base):
    __tablename__ = "commitments"
    source_capture_id: Mapped[str | None] = mapped_column(ForeignKey("captures.id", ondelete="SET NULL"), nullable=True, index=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint("direction IN ('outgoing', 'incoming')", name="ck_commitments_direction"),
        CheckConstraint("status IN ('open', 'done', 'cancelled')", name="ck_commitments_status"),
        Index("ix_commitments_owner_status", "owner_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    notes: Mapped[str] = mapped_column(Text, default="")
    direction: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class WorkCheckpoint(Base):
    __tablename__ = "work_checkpoints"
    __table_args__ = (Index("ix_work_checkpoints_owner_archived", "owner_id", "archived"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    progress: Mapped[str] = mapped_column(Text, default="")
    blocker: Mapped[str] = mapped_column(Text, default="")
    next_step: Mapped[str] = mapped_column(Text)
    resources: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class FocusSession(Base):
    __tablename__ = "focus_sessions"
    companion_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    companion_goal: Mapped[str] = mapped_column(Text, default="", server_default="")
    __table_args__ = (
        CheckConstraint("planned_minutes BETWEEN 1 AND 180", name="ck_focus_planned_minutes"),
        CheckConstraint("outcome IS NULL OR outcome IN ('finished', 'interrupted')", name="ck_focus_outcome"),
        CheckConstraint("elapsed_seconds IS NULL OR elapsed_seconds >= 0", name="ck_focus_elapsed"),
        Index("uq_focus_active_owner", "owner_id", unique=True, postgresql_where=text("ended_at IS NULL"), sqlite_where=text("ended_at IS NULL")),
        Index("ix_focus_owner_started", "owner_id", "started_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    task_title: Mapped[str] = mapped_column(String(240))
    planned_minutes: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    elapsed_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    checkpoint_id: Mapped[str | None] = mapped_column(ForeignKey("work_checkpoints.id", ondelete="SET NULL"), nullable=True)


class TaskStep(Base):
    __tablename__ = "task_steps"
    __table_args__ = (
        UniqueConstraint("task_id", "position", name="uq_task_steps_position"),
        CheckConstraint("estimated_minutes IS NULL OR estimated_minutes BETWEEN 1 AND 180", name="ck_task_steps_minutes"),
        Index("ix_task_steps_owner_task", "owner_id", "task_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(240))
    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class FocusCheckIn(Base):
    __tablename__ = "focus_checkins"
    __table_args__ = (
        CheckConstraint("state IN ('on_track', 'distracted', 'blocked', 'skip')", name="ck_focus_checkin_state"),
        UniqueConstraint("session_id", "request_id", name="uq_focus_checkin_request"),
        Index("ix_focus_checkins_session_created", "session_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("focus_sessions.id", ondelete="CASCADE"))
    request_id: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(Text, default="")
    next_step: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Routine(Base):
    __tablename__ = "routines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    weekdays: Mapped[list[int]] = mapped_column(JSON)
    window_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    window_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RoutineStep(Base):
    __tablename__ = "routine_steps"
    __table_args__ = (UniqueConstraint("routine_id", "position", name="uq_routine_steps_position"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    routine_id: Mapped[str] = mapped_column(ForeignKey("routines.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    position: Mapped[int] = mapped_column(Integer)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class RoutineCompletion(Base):
    __tablename__ = "routine_completions"
    __table_args__ = (
        UniqueConstraint("step_id", "local_date", name="uq_routine_completion_day"),
        Index("ix_routine_completion_date", "local_date"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    step_id: Mapped[str] = mapped_column(ForeignKey("routine_steps.id", ondelete="CASCADE"), index=True)
    local_date: Mapped[date] = mapped_column(Date)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CaptureKey(Base):
    __tablename__ = "capture_keys"
    scope: Mapped[str] = mapped_column(String(24), default="capture:write", server_default="capture:write")
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint_hash: Mapped[str] = mapped_column(String(64), unique=True)
    endpoint: Mapped[str] = mapped_column(Text)
    p256dh: Mapped[str] = mapped_column(String(120))
    auth: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(120))
    token_version: Mapped[int] = mapped_column(Integer)
    vapid_public_key: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sent_keys: Mapped[list[str]] = mapped_column(JSON, default=list)


class DavKey(Base):
    __tablename__ = "dav_keys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(24), default="calendar:read")
    label: Mapped[str] = mapped_column(String(120))
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TemporalFact(Base):
    __tablename__ = "temporal_facts"
    __table_args__ = (
        CheckConstraint("status IN ('proposed', 'confirmed', 'rejected')", name="ck_temporal_fact_status"),
        CheckConstraint("confidence IN ('low', 'medium', 'high')", name="ck_temporal_fact_confidence"),
        CheckConstraint("valid_from IS NULL OR valid_until IS NULL OR valid_from < valid_until", name="ck_temporal_fact_period"),
        Index("ix_temporal_facts_subject", "owner_id", "person_id", "predicate"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    predicate: Mapped[str] = mapped_column(String(120))
    value: Mapped[str] = mapped_column(Text)
    value_key: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    confidence: Mapped[str] = mapped_column(String(10), default="medium")
    status: Mapped[str] = mapped_column(String(12), default="proposed")
    source_note: Mapped[str] = mapped_column(Text, default="")
    source_capture_id: Mapped[str | None] = mapped_column(ForeignKey("captures.id", ondelete="SET NULL"), nullable=True, index=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class FactConflictDecision(Base):
    __tablename__ = "fact_conflict_decisions"
    __table_args__ = (
        CheckConstraint("action IN ('changed', 'both', 'reject_a', 'reject_b', 'defer')", name="ck_fact_conflict_action"),
        Index("ix_fact_conflict_pair", "owner_id", "fact_a_id", "fact_b_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    fact_a_id: Mapped[str] = mapped_column(ForeignKey("temporal_facts.id", ondelete="CASCADE"))
    fact_b_id: Mapped[str] = mapped_column(ForeignKey("temporal_facts.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(12))
    note: Mapped[str] = mapped_column(Text, default="")
    a_revision: Mapped[int] = mapped_column(Integer)
    b_revision: Mapped[int] = mapped_column(Integer)
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class FaceTrainingCard(Base):
    __tablename__ = "face_training_cards"
    __table_args__ = (
        UniqueConstraint("owner_id", "person_id", name="uq_face_training_person"),
        CheckConstraint("level BETWEEN 0 AND 7", name="ck_face_training_level"),
        Index("ix_face_training_due", "owner_id", "active", "due_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"))
    photo_key: Mapped[str] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    level: Mapped[int] = mapped_column(Integer, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DocumentIndex(Base):
    __tablename__ = "document_indexes"
    id: Mapped[str] = mapped_column(ForeignKey("attachments.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    digest: Mapped[str] = mapped_column(String(64))
    total_pages: Mapped[int] = mapped_column(Integer)
    partial: Mapped[bool] = mapped_column(Boolean)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (Index("ix_document_pages_owner", "owner_id", "document_id"),)
    document_id: Mapped[str] = mapped_column(ForeignKey("document_indexes.id", ondelete="CASCADE"), primary_key=True)
    page: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(12))
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)


class DecisionEntry(Base):
    __tablename__ = "decision_entries"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'closed')", name="ck_decision_status"),
        Index("ix_decision_due", "owner_id", "status", "review_on"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    memory_id: Mapped[str | None] = mapped_column(ForeignKey("memories.id", ondelete="SET NULL"), nullable=True)
    attachment_id: Mapped[str | None] = mapped_column(ForeignKey("attachments.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    decided_on: Mapped[date] = mapped_column(Date)
    choice: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    alternatives: Mapped[list] = mapped_column(JSON, default=list)
    expected_outcome: Mapped[str] = mapped_column(Text, default="")
    review_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="open")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DecisionReview(Base):
    __tablename__ = "decision_reviews"
    __table_args__ = (
        UniqueConstraint("decision_id", "revision", name="uq_decision_review_revision"),
        CheckConstraint("assessment IN ('better', 'as_expected', 'worse', 'unclear')", name="ck_decision_assessment"),
        Index("ix_decision_review_owner", "owner_id", "decision_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    decision_id: Mapped[str] = mapped_column(ForeignKey("decision_entries.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer)
    assessment: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(Text)
    lessons: Mapped[str] = mapped_column(Text, default="")
    next_review_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    closed: Mapped[bool] = mapped_column(Boolean)
    reviewed_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Place(Base):
    __tablename__ = "places"
    __table_args__ = (
        CheckConstraint("(latitude IS NULL AND longitude IS NULL) OR (latitude IS NOT NULL AND longitude IS NOT NULL AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)", name="ck_place_coordinates"),
        Index("ix_places_owner_name", "owner_id", "name"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    category: Mapped[str] = mapped_column(String(120), default="")
    address: Mapped[str] = mapped_column(String(500), default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PlaceEntry(Base):
    __tablename__ = "place_entries"
    __table_args__ = (
        CheckConstraint("kind IN ('visit', 'meeting', 'recommendation', 'memory', 'reference')", name="ck_place_entry_kind"),
        Index("ix_place_entries_place", "owner_id", "place_id", "occurred_on"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    place_id: Mapped[str] = mapped_column(ForeignKey("places.id", ondelete="CASCADE"))
    person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), nullable=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    memory_id: Mapped[str | None] = mapped_column(ForeignKey("memories.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(240))
    notes: Mapped[str] = mapped_column(Text, default="")
    occurred_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        CheckConstraint("ownership IN ('own', 'other', 'unknown')", name="ck_inventory_ownership"),
        CheckConstraint("maintenance_interval_days IS NULL OR maintenance_interval_days BETWEEN 1 AND 3650", name="ck_inventory_interval"),
        Index("ix_inventory_due", "owner_id", "archived", "next_maintenance_on"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    category: Mapped[str] = mapped_column(String(120), default="")
    serial_number: Mapped[str] = mapped_column(String(240), default="")
    ownership: Mapped[str] = mapped_column(String(12), default="unknown")
    owner_person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), nullable=True)
    place_id: Mapped[str | None] = mapped_column(ForeignKey("places.id", ondelete="SET NULL"), nullable=True)
    location_detail: Mapped[str] = mapped_column(String(500), default="")
    purchase_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    warranty_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    receipt_attachment_id: Mapped[str | None] = mapped_column(ForeignKey("attachments.id", ondelete="SET NULL"), nullable=True)
    maintenance_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_maintenance_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class InventoryHistory(Base):
    __tablename__ = "inventory_history"
    __table_args__ = (
        CheckConstraint("kind IN ('location', 'maintenance', 'loan_link')", name="ck_inventory_history_kind"),
        Index("ix_inventory_history_item", "owner_id", "item_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    occurred_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    details: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class InventoryLoan(Base):
    __tablename__ = "inventory_loans"
    loan_id: Mapped[str] = mapped_column(ForeignKey("loans.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"), index=True)
