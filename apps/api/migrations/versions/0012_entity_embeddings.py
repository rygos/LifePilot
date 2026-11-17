from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0012_entity_embeddings"
down_revision = "0011_memory_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entity_embeddings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True),
        sa.Column("relationship_id", sa.String(36), sa.ForeignKey("relationships.id", ondelete="CASCADE"), nullable=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(entity_type = 'conversation' AND conversation_id = entity_id AND task_id IS NULL AND relationship_id IS NULL AND project_id IS NULL) OR (entity_type = 'task' AND task_id = entity_id AND conversation_id IS NULL AND relationship_id IS NULL AND project_id IS NULL) OR (entity_type = 'relationship' AND relationship_id = entity_id AND conversation_id IS NULL AND task_id IS NULL AND project_id IS NULL) OR (entity_type = 'project' AND project_id = entity_id AND conversation_id IS NULL AND task_id IS NULL AND relationship_id IS NULL)",
            name="ck_entity_embeddings_single_target",
        ),
        sa.UniqueConstraint("conversation_id", name="uq_entity_embeddings_conversation"),
        sa.UniqueConstraint("task_id", name="uq_entity_embeddings_task"),
        sa.UniqueConstraint("relationship_id", name="uq_entity_embeddings_relationship"),
        sa.UniqueConstraint("project_id", name="uq_entity_embeddings_project"),
    )
    op.create_index("ix_entity_embeddings_owner_id", "entity_embeddings", ["owner_id"])
    op.create_index("ix_entity_embeddings_entity_type", "entity_embeddings", ["entity_type"])
    if op.get_bind().dialect.name == "postgresql":
        op.create_index(
            "ix_entity_embeddings_vector",
            "entity_embeddings",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("ix_entity_embeddings_vector", table_name="entity_embeddings")
    op.drop_index("ix_entity_embeddings_entity_type", table_name="entity_embeddings")
    op.drop_index("ix_entity_embeddings_owner_id", table_name="entity_embeddings")
    op.drop_table("entity_embeddings")
