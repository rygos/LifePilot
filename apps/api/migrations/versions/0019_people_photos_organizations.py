from alembic import op
import sqlalchemy as sa


revision = "0019_people_photos_organizations"
down_revision = "0018_capture_chat_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("people") as batch:
        batch.add_column(sa.Column("photo_key", sa.String(length=80), nullable=True))
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("organization_type", sa.String(length=40), nullable=False, server_default="club"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_id", "normalized_name", name="uq_organizations_owner_name"),
    )
    op.create_index("ix_organizations_owner_id", "organizations", ["owner_id"])
    op.create_table(
        "person_organizations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.String(length=36), sa.ForeignKey("people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_id", "person_id", "organization_id", name="uq_person_organization_membership"),
    )
    op.create_index("ix_person_organizations_owner_id", "person_organizations", ["owner_id"])
    op.create_index("ix_person_organizations_person_id", "person_organizations", ["person_id"])
    op.create_index("ix_person_organizations_organization_id", "person_organizations", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_person_organizations_organization_id", table_name="person_organizations")
    op.drop_index("ix_person_organizations_person_id", table_name="person_organizations")
    op.drop_index("ix_person_organizations_owner_id", table_name="person_organizations")
    op.drop_table("person_organizations")
    op.drop_index("ix_organizations_owner_id", table_name="organizations")
    op.drop_table("organizations")
    with op.batch_alter_table("people") as batch:
        batch.drop_column("photo_key")
