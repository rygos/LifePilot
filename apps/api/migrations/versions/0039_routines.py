from alembic import op
import sqlalchemy as sa

revision = "0039_routines"
down_revision = "0038_focus_companion"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "routines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("weekdays", sa.JSON(), nullable=False),
        sa.Column("window_start", sa.Time()),
        sa.Column("window_end", sa.Time()),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_routines_owner_id", "routines", ["owner_id"])
    op.create_table(
        "routine_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("routine_id", sa.String(36), sa.ForeignKey("routines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("routine_id", "position", name="uq_routine_steps_position"),
    )
    op.create_index("ix_routine_steps_routine_id", "routine_steps", ["routine_id"])
    op.create_table(
        "routine_completions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("step_id", sa.String(36), sa.ForeignKey("routine_steps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("step_id", "local_date", name="uq_routine_completion_day"),
    )
    op.create_index("ix_routine_completions_step_id", "routine_completions", ["step_id"])
    op.create_index("ix_routine_completion_date", "routine_completions", ["local_date"])


def downgrade():
    op.drop_table("routine_completions")
    op.drop_table("routine_steps")
    op.drop_table("routines")
