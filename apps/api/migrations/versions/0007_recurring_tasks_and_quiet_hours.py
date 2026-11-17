from alembic import op
import sqlalchemy as sa

revision = "0007_quiet_hours_repeat"
down_revision = "0006_enable_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("timezone_name", sa.String(64), server_default="Europe/Berlin", nullable=False))
    op.add_column("users", sa.Column("quiet_hours_start", sa.Time(), nullable=True))
    op.add_column("users", sa.Column("quiet_hours_end", sa.Time(), nullable=True))
    op.add_column("tasks", sa.Column("repeat_interval_days", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("repeat_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "repeat_until")
    op.drop_column("tasks", "repeat_interval_days")
    op.drop_column("users", "quiet_hours_end")
    op.drop_column("users", "quiet_hours_start")
    op.drop_column("users", "timezone_name")
