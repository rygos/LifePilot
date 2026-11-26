from alembic import op
import sqlalchemy as sa

revision = "0033_commitments_checkpoints"
down_revision = "0032_token_version"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commitments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="SET NULL")),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("direction IN ('outgoing', 'incoming')", name="ck_commitments_direction"),
        sa.CheckConstraint("status IN ('open', 'done', 'cancelled')", name="ck_commitments_status"),
    )
    op.create_index("ix_commitments_owner_id", "commitments", ["owner_id"])
    op.create_index("ix_commitments_owner_status", "commitments", ["owner_id", "status"])
    op.create_table(
        "work_checkpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("progress", sa.Text(), nullable=False),
        sa.Column("blocker", sa.Text(), nullable=False),
        sa.Column("next_step", sa.Text(), nullable=False),
        sa.Column("resources", sa.Text(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_work_checkpoints_owner_id", "work_checkpoints", ["owner_id"])
    op.create_index("ix_work_checkpoints_owner_archived", "work_checkpoints", ["owner_id", "archived"])


def downgrade():
    op.drop_table("work_checkpoints")
    op.drop_table("commitments")
