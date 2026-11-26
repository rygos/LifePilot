from alembic import op
import sqlalchemy as sa

revision = "0048_document_index"
down_revision = "0047_face_training"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("document_indexes",
        sa.Column("id", sa.String(36), sa.ForeignKey("attachments.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("total_pages", sa.Integer(), nullable=False),
        sa.Column("partial", sa.Boolean(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_document_indexes_owner_id", "document_indexes", ["owner_id"])
    op.create_table("document_pages",
        sa.Column("document_id", sa.String(36), sa.ForeignKey("document_indexes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("page", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("method", sa.String(12), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False))
    op.create_index("ix_document_pages_owner", "document_pages", ["owner_id","document_id"])


def downgrade():
    op.drop_table("document_pages")
    op.drop_table("document_indexes")
