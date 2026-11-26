from alembic import op
import sqlalchemy as sa

revision = "0045_temporal_facts"
down_revision = "0044_integration_key_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "temporal_facts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("predicate", sa.String(120), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_until", sa.Date()),
        sa.Column("confidence", sa.String(10), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.Column("source_capture_id", sa.String(36), sa.ForeignKey("captures.id", ondelete="SET NULL")),
        sa.Column("source_quote", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('proposed', 'confirmed', 'rejected')", name="ck_temporal_fact_status"),
        sa.CheckConstraint("confidence IN ('low', 'medium', 'high')", name="ck_temporal_fact_confidence"),
        sa.CheckConstraint("valid_from IS NULL OR valid_until IS NULL OR valid_from < valid_until", name="ck_temporal_fact_period"),
    )
    for col in ("owner_id", "person_id", "source_capture_id"):
        op.create_index("ix_temporal_facts_" + col, "temporal_facts", [col])
    op.create_index("ix_temporal_facts_subject", "temporal_facts", ["owner_id", "person_id", "predicate"])


def downgrade():
    op.drop_table("temporal_facts")
