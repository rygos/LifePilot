from alembic import op
import sqlalchemy as sa

revision = "0002_phase1_domains"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("original_note", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("location", sa.String(240), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_conversations_owner_id", "conversations", ["owner_id"])
    op.create_index("ix_conversations_occurred_at", "conversations", ["occurred_at"])
    op.create_table("conversation_participants",
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False))
    op.create_index("ix_conversation_participants_owner_id", "conversation_participants", ["owner_id"])
    op.create_table("loans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_name", sa.String(240), nullable=False),
        sa.Column("lender_person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="SET NULL")),
        sa.Column("borrower_person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="SET NULL")),
        sa.Column("lent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("returned_at", sa.DateTime(timezone=True)),
        sa.Column("condition_note", sa.Text(), nullable=False),
        sa.Column("source_memory_id", sa.String(36), sa.ForeignKey("memories.id", ondelete="SET NULL")))
    op.create_index("ix_loans_owner_id", "loans", ["owner_id"])
    op.create_table("gifts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("occasion", sa.String(120), nullable=False),
        sa.Column("budget", sa.Integer()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source_memory_id", sa.String(36), sa.ForeignKey("memories.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for name, column in [("owner_id", "owner_id"), ("person_id", "person_id"), ("status", "status")]:
        op.create_index(f"ix_gifts_{name}", "gifts", [column])

def downgrade():
    op.drop_table("gifts")
    op.drop_table("loans")
    op.drop_table("conversation_participants")
    op.drop_table("conversations")
