from alembic import op
import sqlalchemy as sa

revision = "0016_capture_threads"
down_revision = "0015_user_person_relationships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("captures") as batch:
        batch.add_column(sa.Column("parent_capture_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_captures_parent_capture_id_captures",
            "captures",
            ["parent_capture_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_captures_parent_capture_id", ["parent_capture_id"])


def downgrade() -> None:
    with op.batch_alter_table("captures") as batch:
        batch.drop_index("ix_captures_parent_capture_id")
        batch.drop_constraint("fk_captures_parent_capture_id_captures", type_="foreignkey")
        batch.drop_column("parent_capture_id")
