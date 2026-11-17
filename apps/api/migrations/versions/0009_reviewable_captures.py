from alembic import op
import sqlalchemy as sa

revision = "0009_reviewable_captures"
down_revision = "0008_audit_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "captures",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("suggestions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("processing_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_captures_owner_id", "captures", ["owner_id"])
    op.create_index("ix_captures_status", "captures", ["status"])
    op.create_index("ix_captures_created_at", "captures", ["created_at"])
    with op.batch_alter_table("memories") as batch_op:
        batch_op.add_column(sa.Column("source_capture_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key("fk_memories_source_capture_id_captures", "captures", ["source_capture_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_memories_source_capture_id", "memories", ["source_capture_id"])


def downgrade() -> None:
    op.drop_index("ix_memories_source_capture_id", table_name="memories")
    with op.batch_alter_table("memories") as batch_op:
        batch_op.drop_constraint("fk_memories_source_capture_id_captures", type_="foreignkey")
        batch_op.drop_column("source_capture_id")
    op.drop_index("ix_captures_created_at", table_name="captures")
    op.drop_index("ix_captures_status", table_name="captures")
    op.drop_index("ix_captures_owner_id", table_name="captures")
    op.drop_table("captures")
