from alembic import op
import sqlalchemy as sa


revision = "0025_birthday_reminders"
down_revision = "0024_person_favorites_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("reminders") as batch_op:
        batch_op.add_column(sa.Column("birthday_person_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("birthday_year", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_reminders_birthday_person_id_people",
            "people",
            ["birthday_person_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_reminders_birthday_person_id", ["birthday_person_id"])
        batch_op.create_unique_constraint(
            "uq_reminders_birthday_person_year",
            ["birthday_person_id", "birthday_year"],
        )


def downgrade() -> None:
    with op.batch_alter_table("reminders") as batch_op:
        batch_op.drop_constraint("uq_reminders_birthday_person_year", type_="unique")
        batch_op.drop_index("ix_reminders_birthday_person_id")
        batch_op.drop_constraint("fk_reminders_birthday_person_id_people", type_="foreignkey")
        batch_op.drop_column("birthday_year")
        batch_op.drop_column("birthday_person_id")
