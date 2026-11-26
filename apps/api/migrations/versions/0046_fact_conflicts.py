from hashlib import sha256
from unicodedata import normalize

from alembic import op
import sqlalchemy as sa

revision = "0046_fact_conflicts"
down_revision = "0045_temporal_facts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("temporal_facts", sa.Column("revision", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("temporal_facts", sa.Column("value_key", sa.String(64), nullable=False, server_default=""))
    table = sa.table("temporal_facts", sa.column("id", sa.String), sa.column("value", sa.Text), sa.column("value_key", sa.String))
    bind = op.get_bind()
    # Keyset batches bound memory during migration.
    last = ""
    while True:
        rows = bind.execute(sa.select(table.c.id, table.c.value).where(table.c.id > last).order_by(table.c.id).limit(500)).all()
        if not rows:
            break
        for row in rows:
            key = sha256(" ".join(normalize("NFC", row.value).casefold().split()).encode()).hexdigest()
            bind.execute(table.update().where(table.c.id == row.id).values(value_key=key))
        last = rows[-1].id
    with op.batch_alter_table("temporal_facts") as batch:
        batch.alter_column("value_key", server_default=None)
    op.create_table(
        "fact_conflict_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fact_a_id", sa.String(36), sa.ForeignKey("temporal_facts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fact_b_id", sa.String(36), sa.ForeignKey("temporal_facts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("a_revision", sa.Integer(), nullable=False),
        sa.Column("b_revision", sa.Integer(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('changed', 'both', 'reject_a', 'reject_b', 'defer')", name="ck_fact_conflict_action"),
    )
    for col in ("owner_id", "person_id"):
        op.create_index("ix_fact_conflict_decisions_" + col, "fact_conflict_decisions", [col])
    op.create_index("ix_fact_conflict_pair", "fact_conflict_decisions", ["owner_id", "fact_a_id", "fact_b_id"])


def downgrade():
    op.drop_table("fact_conflict_decisions")
    op.drop_column("temporal_facts", "value_key")
    op.drop_column("temporal_facts", "revision")
