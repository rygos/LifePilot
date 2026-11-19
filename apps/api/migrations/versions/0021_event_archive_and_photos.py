from alembic import op
import sqlalchemy as sa


revision = "0021_event_archive_and_photos"
down_revision = "0020_person_gender"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch:
        batch.add_column(sa.Column("record_type", sa.String(length=20), nullable=False, server_default="appointment"))
        batch.add_column(sa.Column("location_address", sa.String(length=500), nullable=False, server_default=""))
        batch.create_index("ix_events_record_type", ["record_type"])
    op.create_table(
        "event_photos",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(length=36), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_key", sa.String(length=80), nullable=False),
        sa.Column("caption", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_event_photos_owner_id", "event_photos", ["owner_id"])
    op.create_index("ix_event_photos_event_id", "event_photos", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_event_photos_event_id", table_name="event_photos")
    op.drop_index("ix_event_photos_owner_id", table_name="event_photos")
    op.drop_table("event_photos")
    with op.batch_alter_table("events") as batch:
        batch.drop_index("ix_events_record_type")
        batch.drop_column("location_address")
        batch.drop_column("record_type")
