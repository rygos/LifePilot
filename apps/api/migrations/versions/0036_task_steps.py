from alembic import op
import sqlalchemy as sa

revision = "0036_task_steps"
down_revision = "0035_focus_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "task_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("estimated_minutes", sa.Integer()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "position", name="uq_task_steps_position"),
        sa.CheckConstraint("estimated_minutes IS NULL OR estimated_minutes BETWEEN 1 AND 180", name="ck_task_steps_minutes"),
    )
    op.create_index("ix_task_steps_owner_task", "task_steps", ["owner_id", "task_id"])


def downgrade():
    op.drop_table("task_steps")
