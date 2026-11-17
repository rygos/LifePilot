from alembic import op
import sqlalchemy as sa

revision = "0015_user_person_relationships"
down_revision = "0014_resource_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_person_relationships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relationship_type", sa.String(100), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("source_capture_id", sa.String(36), sa.ForeignKey("captures.id", ondelete="SET NULL")),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_person_relationships_owner_id", "user_person_relationships", ["owner_id"])
    op.create_index("ix_user_person_relationships_person_id", "user_person_relationships", ["person_id"])


def downgrade() -> None:
    op.drop_index("ix_user_person_relationships_person_id", table_name="user_person_relationships")
    op.drop_index("ix_user_person_relationships_owner_id", table_name="user_person_relationships")
    op.drop_table("user_person_relationships")
