from alembic import op
import sqlalchemy as sa

revision = "0049_decision_journal"
down_revision = "0048_document_index"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("decision_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="SET NULL")),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("memory_id", sa.String(36), sa.ForeignKey("memories.id", ondelete="SET NULL")),
        sa.Column("attachment_id", sa.String(36), sa.ForeignKey("attachments.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("decided_on", sa.Date(), nullable=False),
        sa.Column("choice", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("alternatives", sa.JSON(), nullable=False),
        sa.Column("expected_outcome", sa.Text(), nullable=False),
        sa.Column("review_on", sa.Date()),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('open', 'closed')", name="ck_decision_status"))
    op.create_index("ix_decision_entries_owner_id", "decision_entries", ["owner_id"])
    op.create_index("ix_decision_due", "decision_entries", ["owner_id","status","review_on"])
    op.create_table("decision_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision_id", sa.String(36), sa.ForeignKey("decision_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("assessment", sa.String(16), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("lessons", sa.Text(), nullable=False),
        sa.Column("next_review_on", sa.Date()),
        sa.Column("closed", sa.Boolean(), nullable=False),
        sa.Column("reviewed_on", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("decision_id","revision",name="uq_decision_review_revision"),
        sa.CheckConstraint("assessment IN ('better', 'as_expected', 'worse', 'unclear')",name="ck_decision_assessment"))
    op.create_index("ix_decision_review_owner","decision_reviews",["owner_id","decision_id"])


def downgrade():
    op.drop_table("decision_reviews")
    op.drop_table("decision_entries")
