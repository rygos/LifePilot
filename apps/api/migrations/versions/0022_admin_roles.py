from alembic import op
import sqlalchemy as sa


revision = "0022_admin_roles"
down_revision = "0021_event_archive_and_photos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("role", sa.String(length=20), nullable=False, server_default="user"))
        batch.create_check_constraint("ck_users_role", "role IN ('user', 'admin')")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_role", type_="check")
        batch.drop_column("role")
