from alembic import op
import sqlalchemy as sa

revision = "0035_focus_sessions"
down_revision = "0034_task_planning"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "focus_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("task_title", sa.String(240), nullable=False),
        sa.Column("planned_minutes", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("elapsed_seconds", sa.Integer()),
        sa.Column("outcome", sa.String(16)),
        sa.Column("checkpoint_id", sa.String(36), sa.ForeignKey("work_checkpoints.id", ondelete="SET NULL")),
        sa.CheckConstraint("planned_minutes BETWEEN 1 AND 180", name="ck_focus_planned_minutes"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('finished', 'interrupted')", name="ck_focus_outcome"),
        sa.CheckConstraint("elapsed_seconds IS NULL OR elapsed_seconds >= 0", name="ck_focus_elapsed"),
    )
    op.create_index("ix_focus_sessions_owner_id", "focus_sessions", ["owner_id"])
    op.create_index("ix_focus_owner_started", "focus_sessions", ["owner_id", "started_at"])
    op.create_index("uq_focus_active_owner", "focus_sessions", ["owner_id"], unique=True,
                    sqlite_where=sa.text("ended_at IS NULL"), postgresql_where=sa.text("ended_at IS NULL"))


def downgrade():
    op.drop_table("focus_sessions")
