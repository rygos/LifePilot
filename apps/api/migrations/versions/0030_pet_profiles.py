from alembic import op
import sqlalchemy as sa


revision = "0030_pet_profiles"
down_revision = "0029_journal_entries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("species", sa.String(length=80), nullable=False),
        sa.Column("breed", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("sex", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("birthday", sa.Date(), nullable=True),
        sa.Column("is_neutered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("sex IN ('female', 'male', 'unknown')", name="ck_pets_sex"),
    )
    op.create_index("ix_pets_owner_id", "pets", ["owner_id"])
    op.create_index("ix_pets_owner_name", "pets", ["owner_id", "name"])
    for table_name, target_name, target_column in (
        ("pet_people", "people", "person_id"),
        ("pet_events", "events", "event_id"),
    ):
        columns = [
            sa.Column("pet_id", sa.String(length=36), sa.ForeignKey("pets.id", ondelete="CASCADE"), primary_key=True),
            sa.Column(target_column, sa.String(length=36), sa.ForeignKey(f"{target_name}.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("owner_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        ]
        if table_name == "pet_people":
            columns.append(sa.Column("relationship_type", sa.String(length=20), nullable=False, server_default="owner"))
            columns.append(sa.CheckConstraint("relationship_type IN ('owner', 'caretaker', 'lives_with')", name="ck_pet_people_relationship_type"))
        op.create_table(table_name, *columns)
        op.create_index(f"ix_{table_name}_owner_id", table_name, ["owner_id"])


def downgrade() -> None:
    for table_name in ("pet_events", "pet_people"):
        op.drop_index(f"ix_{table_name}_owner_id", table_name=table_name)
        op.drop_table(table_name)
    op.drop_index("ix_pets_owner_name", table_name="pets")
    op.drop_index("ix_pets_owner_id", table_name="pets")
    op.drop_table("pets")
