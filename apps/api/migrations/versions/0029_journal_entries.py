from alembic import op
import sqlalchemy as sa


revision = "0029_journal_entries"
down_revision = "0028_project_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mood", sa.String(length=24), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("mood IS NULL OR mood IN ('freudig', 'ruhig', 'neutral', 'traurig', 'gestresst', 'dankbar', 'energiegeladen')", name="ck_journal_entries_mood"),
    )
    op.create_index("ix_journal_entries_owner_id", "journal_entries", ["owner_id"])
    op.create_index("ix_journal_entries_entry_date", "journal_entries", ["entry_date"])
    op.create_index("ix_journal_entries_owner_date", "journal_entries", ["owner_id", "entry_date"])
    for table_name, target_name, target_column in (
        ("journal_entry_people", "people", "person_id"),
        ("journal_entry_projects", "projects", "project_id"),
        ("journal_entry_events", "events", "event_id"),
    ):
        op.create_table(
            table_name,
            sa.Column("entry_id", sa.String(length=36), sa.ForeignKey("journal_entries.id", ondelete="CASCADE"), primary_key=True),
            sa.Column(target_column, sa.String(length=36), sa.ForeignKey(f"{target_name}.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("owner_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        )
        op.create_index(f"ix_{table_name}_owner_id", table_name, ["owner_id"])


def downgrade() -> None:
    for table_name in ("journal_entry_events", "journal_entry_projects", "journal_entry_people"):
        op.drop_index(f"ix_{table_name}_owner_id", table_name=table_name)
        op.drop_table(table_name)
    op.drop_index("ix_journal_entries_owner_date", table_name="journal_entries")
    op.drop_index("ix_journal_entries_entry_date", table_name="journal_entries")
    op.drop_index("ix_journal_entries_owner_id", table_name="journal_entries")
    op.drop_table("journal_entries")
