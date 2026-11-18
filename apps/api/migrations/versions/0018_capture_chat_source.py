from alembic import op
import sqlalchemy as sa


revision = "0018_capture_chat_source"
down_revision = "0017_self_person_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("captures") as batch:
        batch.add_column(sa.Column("source", sa.String(length=20), nullable=False, server_default="capture"))
    op.create_index("ix_captures_source", "captures", ["source"])


def downgrade() -> None:
    op.drop_index("ix_captures_source", table_name="captures")
    with op.batch_alter_table("captures") as batch:
        batch.drop_column("source")
