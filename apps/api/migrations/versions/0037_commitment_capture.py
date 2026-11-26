from alembic import op
import sqlalchemy as sa

revision = "0037_commitment_capture"
down_revision = "0036_task_steps"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("commitments") as batch:
        batch.add_column(sa.Column("source_capture_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("source_quote", sa.Text(), nullable=True))
        batch.create_foreign_key("fk_commitments_source_capture", "captures", ["source_capture_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_commitments_source_capture_id", ["source_capture_id"])


def downgrade():
    with op.batch_alter_table("commitments") as batch:
        batch.drop_index("ix_commitments_source_capture_id")
        batch.drop_constraint("fk_commitments_source_capture", type_="foreignkey")
        batch.drop_column("source_quote")
        batch.drop_column("source_capture_id")
