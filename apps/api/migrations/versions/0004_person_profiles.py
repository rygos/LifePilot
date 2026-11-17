from alembic import op
import sqlalchemy as sa

revision = "0004_person_profiles"
down_revision = "0003_events_reminders"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("full_name", sa.String(240), nullable=False, server_default=""))
        batch.add_column(sa.Column("nickname", sa.String(120)))
        batch.add_column(sa.Column("birthday", sa.String(10)))
        batch.add_column(sa.Column("email", sa.String(320)))
        batch.add_column(sa.Column("phone", sa.String(80)))
        batch.add_column(sa.Column("address", sa.Text(), nullable=False, server_default=""))
    with op.batch_alter_table("people") as batch:
        batch.add_column(sa.Column("address", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("website", sa.String(500)))
        batch.add_column(sa.Column("job_title", sa.String(160)))
        batch.add_column(sa.Column("organization", sa.String(200)))

def downgrade():
    with op.batch_alter_table("people") as batch:
        batch.drop_column("organization")
        batch.drop_column("job_title")
        batch.drop_column("website")
        batch.drop_column("address")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("address")
        batch.drop_column("phone")
        batch.drop_column("email")
        batch.drop_column("birthday")
        batch.drop_column("nickname")
        batch.drop_column("full_name")
