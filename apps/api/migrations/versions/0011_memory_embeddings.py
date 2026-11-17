from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0011_memory_embeddings"
down_revision = "0010_projects_and_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_embeddings",
        sa.Column("memory_id", sa.String(36), sa.ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memory_embeddings_owner_id", "memory_embeddings", ["owner_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.create_index(
            "ix_memory_embeddings_vector",
            "memory_embeddings",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("ix_memory_embeddings_vector", table_name="memory_embeddings")
    op.drop_index("ix_memory_embeddings_owner_id", table_name="memory_embeddings")
    op.drop_table("memory_embeddings")
