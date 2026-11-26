from alembic import op
import sqlalchemy as sa

revision = "0051_inventory"
down_revision = "0050_places"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("inventory_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("serial_number", sa.String(240), nullable=False),
        sa.Column("ownership", sa.String(12), nullable=False),
        sa.Column("owner_person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="SET NULL")),
        sa.Column("place_id", sa.String(36), sa.ForeignKey("places.id", ondelete="SET NULL")),
        sa.Column("location_detail", sa.String(500), nullable=False),
        sa.Column("purchase_on", sa.Date()),
        sa.Column("warranty_until", sa.Date()),
        sa.Column("receipt_attachment_id", sa.String(36), sa.ForeignKey("attachments.id", ondelete="SET NULL")),
        sa.Column("maintenance_interval_days", sa.Integer()),
        sa.Column("next_maintenance_on", sa.Date()),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ownership IN ('own', 'other', 'unknown')",name="ck_inventory_ownership"),
        sa.CheckConstraint("maintenance_interval_days IS NULL OR maintenance_interval_days BETWEEN 1 AND 3650",name="ck_inventory_interval"))
    op.create_index("ix_inventory_items_owner_id","inventory_items",["owner_id"])
    op.create_index("ix_inventory_due","inventory_items",["owner_id","archived","next_maintenance_on"])
    op.create_table("inventory_history",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("owner_id",sa.String(36),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("item_id",sa.String(36),sa.ForeignKey("inventory_items.id",ondelete="CASCADE"),nullable=False),
        sa.Column("kind",sa.String(20),nullable=False),
        sa.Column("occurred_on",sa.Date()),
        sa.Column("details",sa.JSON(),nullable=False),
        sa.Column("note",sa.Text(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("kind IN ('location', 'maintenance', 'loan_link')",name="ck_inventory_history_kind"))
    op.create_index("ix_inventory_history_owner_id","inventory_history",["owner_id"])
    op.create_index("ix_inventory_history_item","inventory_history",["owner_id","item_id","created_at"])
    op.create_table("inventory_loans",
        sa.Column("loan_id",sa.String(36),sa.ForeignKey("loans.id",ondelete="CASCADE"),primary_key=True),
        sa.Column("owner_id",sa.String(36),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("item_id",sa.String(36),sa.ForeignKey("inventory_items.id",ondelete="CASCADE"),nullable=False))
    op.create_index("ix_inventory_loans_owner_id","inventory_loans",["owner_id"])
    op.create_index("ix_inventory_loans_item_id","inventory_loans",["item_id"])


def downgrade():
    op.drop_table("inventory_loans")
    op.drop_table("inventory_history")
    op.drop_table("inventory_items")
