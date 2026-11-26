from alembic import op
import sqlalchemy as sa

revision = "0050_places"
down_revision = "0049_decision_journal"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("places",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("address", sa.String(500), nullable=False),
        sa.Column("latitude", sa.Float()),
        sa.Column("longitude", sa.Float()),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("(latitude IS NULL AND longitude IS NULL) OR (latitude IS NOT NULL AND longitude IS NOT NULL AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)", name="ck_place_coordinates"))
    op.create_index("ix_places_owner_id", "places", ["owner_id"])
    op.create_index("ix_places_owner_name", "places", ["owner_id","name"])
    op.create_table("place_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("place_id", sa.String(36), sa.ForeignKey("places.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="SET NULL")),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id", ondelete="SET NULL")),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="SET NULL")),
        sa.Column("memory_id", sa.String(36), sa.ForeignKey("memories.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("occurred_on", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('visit', 'meeting', 'recommendation', 'memory', 'reference')", name="ck_place_entry_kind"))
    op.create_index("ix_place_entries_owner_id", "place_entries", ["owner_id"])
    op.create_index("ix_place_entries_place", "place_entries", ["owner_id","place_id","occurred_on"])


def downgrade():
    op.drop_table("place_entries")
    op.drop_table("places")
