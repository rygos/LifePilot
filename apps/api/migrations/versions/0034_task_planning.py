from alembic import op
import sqlalchemy as sa

revision = "0034_task_planning"
down_revision = "0033_commitments_checkpoints"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tasks", sa.Column("estimated_minutes", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("mental_effort", sa.String(12), nullable=True))
    op.add_column("tasks", sa.Column("start_friction", sa.String(12), nullable=True))
    op.add_column("tasks", sa.Column("work_context", sa.String(20), nullable=True))
    op.add_column("tasks", sa.Column("next_step", sa.Text(), nullable=True))


def downgrade():
    for name in ("next_step", "work_context", "start_friction", "mental_effort", "estimated_minutes"):
        op.drop_column("tasks", name)
