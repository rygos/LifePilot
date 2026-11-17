from alembic import op
import sqlalchemy as sa

revision = "0014_resource_revisions"
down_revision = "0013_capture_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_type", sa.String(40), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="application"),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "resource_type", "resource_id", "revision", name="uq_resource_revisions_owner_resource_revision"),
    )
    op.create_index("ix_resource_revisions_owner_id", "resource_revisions", ["owner_id"])
    op.create_index("ix_resource_revisions_resource_type", "resource_revisions", ["resource_type"])
    op.create_index("ix_resource_revisions_resource_id", "resource_revisions", ["resource_id"])
    op.create_index("ix_resource_revisions_created_at", "resource_revisions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_resource_revisions_created_at", table_name="resource_revisions")
    op.drop_index("ix_resource_revisions_resource_id", table_name="resource_revisions")
    op.drop_index("ix_resource_revisions_resource_type", table_name="resource_revisions")
    op.drop_index("ix_resource_revisions_owner_id", table_name="resource_revisions")
    op.drop_table("resource_revisions")
