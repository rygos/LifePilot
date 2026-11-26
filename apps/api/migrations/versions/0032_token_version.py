from alembic import op
import sqlalchemy as sa

revision = "0032_token_version"
down_revision = "0031_contact_profile_details"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("users", "token_version")
