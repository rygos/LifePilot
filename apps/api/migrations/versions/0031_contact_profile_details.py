from alembic import op
import sqlalchemy as sa


revision = "0031_contact_profile_details"
down_revision = "0030_pet_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("people") as batch_op:
        batch_op.add_column(sa.Column("birthday_precision", sa.String(length=20), nullable=False, server_default="unknown"))
        batch_op.add_column(sa.Column("birthday_month", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("birthday_day", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("birthday_approximate_age", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("contact_interval_days", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_check_constraint("ck_people_birthday_precision", "birthday_precision IN ('exact', 'month_day', 'approximate', 'unknown')")
        batch_op.create_check_constraint("ck_people_contact_interval_days", "contact_interval_days IS NULL OR contact_interval_days BETWEEN 1 AND 365")
    op.execute("UPDATE people SET birthday_precision = 'exact', birthday_month = CAST(substr(birthday, 6, 2) AS INTEGER), birthday_day = CAST(substr(birthday, 9, 2) AS INTEGER) WHERE birthday IS NOT NULL")

    with op.batch_alter_table("reminders") as batch_op:
        batch_op.add_column(sa.Column("contact_person_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key("fk_reminders_contact_person_id_people", "people", ["contact_person_id"], ["id"], ondelete="CASCADE")
        batch_op.create_index("ix_reminders_contact_person_id", ["contact_person_id"])
        batch_op.create_unique_constraint("uq_reminders_contact_person", ["contact_person_id"])

    op.create_table(
        "person_call_logs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.String(length=36), sa.ForeignKey("people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_person_call_logs_owner_id", "person_call_logs", ["owner_id"])
    op.create_index("ix_person_call_logs_person_id", "person_call_logs", ["person_id"])
    op.create_index("ix_person_call_logs_occurred_at", "person_call_logs", ["occurred_at"])
    op.create_index("ix_person_call_logs_person_occurred", "person_call_logs", ["owner_id", "person_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_person_call_logs_person_occurred", table_name="person_call_logs")
    op.drop_index("ix_person_call_logs_occurred_at", table_name="person_call_logs")
    op.drop_index("ix_person_call_logs_person_id", table_name="person_call_logs")
    op.drop_index("ix_person_call_logs_owner_id", table_name="person_call_logs")
    op.drop_table("person_call_logs")
    with op.batch_alter_table("reminders") as batch_op:
        batch_op.drop_constraint("uq_reminders_contact_person", type_="unique")
        batch_op.drop_index("ix_reminders_contact_person_id")
        batch_op.drop_constraint("fk_reminders_contact_person_id_people", type_="foreignkey")
        batch_op.drop_column("contact_person_id")
    with op.batch_alter_table("people") as batch_op:
        batch_op.drop_constraint("ck_people_contact_interval_days", type_="check")
        batch_op.drop_constraint("ck_people_birthday_precision", type_="check")
        batch_op.drop_column("last_contact_at")
        batch_op.drop_column("contact_interval_days")
        batch_op.drop_column("birthday_approximate_age")
        batch_op.drop_column("birthday_day")
        batch_op.drop_column("birthday_month")
        batch_op.drop_column("birthday_precision")
