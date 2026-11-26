from alembic import op
import sqlalchemy as sa

revision = "0040_capture_idempotency"
down_revision = "0039_routines"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("captures") as batch:
        batch.add_column(sa.Column("client_request_id", sa.String(36), nullable=True))
        batch.create_unique_constraint("uq_capture_client_request", ["owner_id", "client_request_id"])


def downgrade():
    with op.batch_alter_table("captures") as batch:
        batch.drop_constraint("uq_capture_client_request", type_="unique")
        batch.drop_column("client_request_id")
