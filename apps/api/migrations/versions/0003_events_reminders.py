from alembic import op
import sqlalchemy as sa

revision = "0003_events_reminders"
down_revision = "0002_phase1_domains"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(240), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("source_memory_id", sa.String(36), sa.ForeignKey("memories.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_events_owner_id", "events", ["owner_id"])
    op.create_index("ix_events_starts_at", "events", ["starts_at"])
    op.create_table("event_participants",
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False))
    op.create_index("ix_event_participants_owner_id", "event_participants", ["owner_id"])
    op.create_table("reminders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE")),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id", ondelete="CASCADE")),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("snoozed_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", name="uq_reminders_task_id"),
        sa.UniqueConstraint("event_id", name="uq_reminders_event_id"))
    for name, column in [("owner_id", "owner_id"), ("due_at", "due_at"), ("task_id", "task_id"), ("event_id", "event_id"), ("state", "state")]:
        op.create_index(f"ix_reminders_{name}", "reminders", [column])

def downgrade():
    op.drop_table("reminders")
    op.drop_table("event_participants")
    op.drop_table("events")
