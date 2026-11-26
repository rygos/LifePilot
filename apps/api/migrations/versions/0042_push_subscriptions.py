from alembic import op
import sqlalchemy as sa

revision = "0042_push_subscriptions"
down_revision = "0041_capture_keys"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(120), nullable=False),
        sa.Column("auth", sa.String(40), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("vapid_public_key", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True)),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_keys", sa.JSON(), nullable=False),
    )
    op.create_index("ix_push_subscriptions_owner_id", "push_subscriptions", ["owner_id"])
    op.create_index("ix_push_subscriptions_next_check_at", "push_subscriptions", ["next_check_at"])


def downgrade():
    op.drop_table("push_subscriptions")
