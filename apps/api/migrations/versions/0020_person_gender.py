from alembic import op
import sqlalchemy as sa


revision = "0020_person_gender"
down_revision = "0019_people_photos_organizations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("people") as batch:
        batch.add_column(sa.Column("gender", sa.String(length=20), nullable=False, server_default="unspecified"))
        batch.create_check_constraint(
            "ck_people_gender",
            "gender IN ('female', 'male', 'diverse', 'unspecified')",
        )


def downgrade() -> None:
    with op.batch_alter_table("people") as batch:
        batch.drop_constraint("ck_people_gender", type_="check")
        batch.drop_column("gender")
