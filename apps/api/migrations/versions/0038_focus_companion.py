from alembic import op
import sqlalchemy as sa

revision = "0038_focus_companion"
down_revision = "0037_commitment_capture"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("focus_sessions", sa.Column("companion_interval_minutes", sa.Integer(), nullable=True))
    op.add_column("focus_sessions", sa.Column("companion_goal", sa.Text(), nullable=False, server_default=""))
    op.create_table(
        "focus_checkins",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("focus_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("next_step", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state IN ('on_track', 'distracted', 'blocked', 'skip')", name="ck_focus_checkin_state"),
        sa.UniqueConstraint("session_id", "request_id", name="uq_focus_checkin_request"),
    )
    op.create_index("ix_focus_checkins_owner_id", "focus_checkins", ["owner_id"])
    op.create_index("ix_focus_checkins_session_created", "focus_checkins", ["session_id", "created_at"])


def downgrade():
    op.drop_table("focus_checkins")
    op.drop_column("focus_sessions", "companion_goal")
    op.drop_column("focus_sessions", "companion_interval_minutes")
