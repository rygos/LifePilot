from alembic import op
import sqlalchemy as sa

revision = "0044_integration_key_scope"
down_revision = "0043_dav_keys"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("capture_keys", sa.Column("scope", sa.String(24), nullable=False, server_default="capture:write"))


def downgrade():
    op.execute(sa.text("DELETE FROM capture_keys WHERE scope != 'capture:write'"))
    op.drop_column("capture_keys", "scope")
