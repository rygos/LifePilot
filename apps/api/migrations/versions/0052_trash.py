from alembic import op
import sqlalchemy as sa

revision = "0052_trash"
down_revision = "0051_inventory"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("trash_entries",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("owner_id",sa.String(36),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("resource_type",sa.String(40),nullable=False),
        sa.Column("resource_id",sa.String(36),nullable=False),
        sa.Column("label",sa.String(240),nullable=False),
        sa.Column("snapshot",sa.JSON(),nullable=False),
        sa.Column("deleted_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint("owner_id","resource_type","resource_id",name="uq_trash_resource"))
    op.create_index("ix_trash_owner_expiry","trash_entries",["owner_id","expires_at"])
    op.create_index("ix_trash_expiry","trash_entries",["expires_at"])


def downgrade():
    op.drop_table("trash_entries")
