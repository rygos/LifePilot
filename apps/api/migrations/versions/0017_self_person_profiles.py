from datetime import datetime, timezone
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0017_self_person_profiles"
down_revision = "0016_capture_threads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("people") as batch:
        batch.add_column(sa.Column("is_self", sa.Boolean(), nullable=False, server_default=sa.false()))

    connection = op.get_bind()
    users = connection.execute(sa.text("SELECT id, username, full_name, nickname, birthday, email, phone, address FROM users")).mappings()
    existing = set(connection.execute(sa.text("SELECT owner_id FROM people WHERE is_self = true")).scalars())
    now = datetime.now(timezone.utc)
    insert_person = sa.text("INSERT INTO people (id, owner_id, first_name, last_name, nickname, birthday, email, phone, address, notes, is_self, created_at, updated_at) VALUES (:id, :owner_id, :first_name, :last_name, :nickname, :birthday, :email, :phone, :address, '', true, :created_at, :updated_at)")
    for user in users:
        if user["id"] in existing:
            continue
        full_name = (user["full_name"] or "").strip()
        first_name, separator, last_name = full_name.partition(" ")
        connection.execute(
            insert_person,
            {
                "id": str(uuid4()),
                "owner_id": user["id"],
                "first_name": first_name or user["username"],
                "last_name": last_name if separator else "",
                "nickname": user["nickname"],
                "birthday": user["birthday"],
                "email": user["email"],
                "phone": user["phone"],
                "address": user["address"] or "",
                "created_at": now,
                "updated_at": now,
            },
        )

    op.create_index(
        "uq_people_one_self_profile_per_owner",
        "people",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("is_self = true"),
        sqlite_where=sa.text("is_self = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_people_one_self_profile_per_owner", table_name="people")
    with op.batch_alter_table("people") as batch:
        batch.drop_column("is_self")
