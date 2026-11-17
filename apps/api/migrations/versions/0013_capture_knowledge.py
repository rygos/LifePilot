from alembic import op
import sqlalchemy as sa

revision = "0013_capture_knowledge"
down_revision = "0012_entity_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("project_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_tasks_project_id_projects", "projects", ["project_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_tasks_project_id", ["project_id"])
    op.create_table(
        "person_name_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("name_type", sa.String(40), nullable=False, server_default="former"),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("source_capture_id", sa.String(36), sa.ForeignKey("captures.id", ondelete="SET NULL")),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_person_name_history_owner_id", "person_name_history", ["owner_id"])
    op.create_index("ix_person_name_history_person_id", "person_name_history", ["person_id"])
    op.create_table(
        "person_life_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("details", sa.Text(), nullable=False, server_default=""),
        sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("date_precision", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("source_capture_id", sa.String(36), sa.ForeignKey("captures.id", ondelete="SET NULL")),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_person_life_events_owner_id", "person_life_events", ["owner_id"])
    op.create_index("ix_person_life_events_person_id", "person_life_events", ["person_id"])
    op.create_table(
        "conversation_projects",
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_conversation_projects_owner_id", "conversation_projects", ["owner_id"])
    op.create_table(
        "memory_projects",
        sa.Column("memory_id", sa.String(36), sa.ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_memory_projects_owner_id", "memory_projects", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_person_life_events_person_id", table_name="person_life_events")
    op.drop_index("ix_person_life_events_owner_id", table_name="person_life_events")
    op.drop_table("person_life_events")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_index("ix_tasks_project_id")
        batch.drop_constraint("fk_tasks_project_id_projects", type_="foreignkey")
        batch.drop_column("project_id")
    op.drop_index("ix_memory_projects_owner_id", table_name="memory_projects")
    op.drop_table("memory_projects")
    op.drop_index("ix_conversation_projects_owner_id", table_name="conversation_projects")
    op.drop_table("conversation_projects")
    op.drop_index("ix_person_name_history_person_id", table_name="person_name_history")
    op.drop_index("ix_person_name_history_owner_id", table_name="person_name_history")
    op.drop_table("person_name_history")
