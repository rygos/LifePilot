from alembic import op
import sqlalchemy as sa

revision = "0041_capture_keys"
down_revision = "0040_capture_idempotency"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "capture_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("window_started_at", sa.DateTime(timezone=True)),
        sa.Column("window_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_capture_keys_owner_id", "capture_keys", ["owner_id"])


def downgrade():
    op.drop_table("capture_keys")
