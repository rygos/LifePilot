from alembic import op
import sqlalchemy as sa


revision = "0027_resource_attachments"
down_revision = "0026_person_contact_methods"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_type", sa.String(length=24), nullable=False),
        sa.Column("resource_id", sa.String(length=36), nullable=False),
        sa.Column("storage_key", sa.String(length=120), nullable=False, unique=True),
        sa.Column("file_name", sa.String(length=240), nullable=False),
        sa.Column("content_type", sa.String(length=160), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("resource_type IN ('person', 'memory', 'conversation', 'event')", name="ck_attachments_resource_type"),
    )
    op.create_index("ix_attachments_owner_id", "attachments", ["owner_id"])
    op.create_index("ix_attachments_owner_resource", "attachments", ["owner_id", "resource_type", "resource_id"])


def downgrade() -> None:
    op.drop_index("ix_attachments_owner_resource", table_name="attachments")
    op.drop_index("ix_attachments_owner_id", table_name="attachments")
    op.drop_table("attachments")
