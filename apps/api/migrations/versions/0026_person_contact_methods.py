from alembic import op
import sqlalchemy as sa


revision = "0026_person_contact_methods"
down_revision = "0025_birthday_reminders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "person_contact_methods",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("person_id", sa.String(length=36), nullable=False),
        sa.Column("method_type", sa.String(length=24), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("value", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "person_id", "method_type", "label", "value", name="uq_person_contact_method_value"),
    )
    op.create_index("ix_person_contact_methods_owner_id", "person_contact_methods", ["owner_id"])
    op.create_index("ix_person_contact_methods_person_id", "person_contact_methods", ["person_id"])


def downgrade() -> None:
    op.drop_index("ix_person_contact_methods_person_id", table_name="person_contact_methods")
    op.drop_index("ix_person_contact_methods_owner_id", table_name="person_contact_methods")
    op.drop_table("person_contact_methods")
