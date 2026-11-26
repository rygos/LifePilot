from alembic import op
import sqlalchemy as sa

revision = "0053_family_spaces"
down_revision = "0052_trash"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("family_spaces",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("owner_id",sa.String(36),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("name",sa.String(120),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_family_spaces_owner_id","family_spaces",["owner_id"])
    op.create_table("family_memberships",
        sa.Column("space_id",sa.String(36),sa.ForeignKey("family_spaces.id",ondelete="CASCADE"),primary_key=True),
        sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id",ondelete="CASCADE"),primary_key=True),
        sa.Column("role",sa.String(12),nullable=False),
        sa.Column("state",sa.String(12),nullable=False),
        sa.Column("invited_at",sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("role IN ('viewer', 'editor')",name="ck_family_role"),
        sa.CheckConstraint("state IN ('pending', 'active')",name="ck_family_state"))
    op.create_index("ix_family_memberships_user_id","family_memberships",["user_id"])
    op.create_table("family_shares",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("space_id",sa.String(36),sa.ForeignKey("family_spaces.id",ondelete="CASCADE"),nullable=False),
        sa.Column("owner_id",sa.String(36),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("kind",sa.String(12),nullable=False),
        sa.Column("resource_id",sa.String(36),nullable=False),
        sa.Column("snapshot",sa.JSON(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint("space_id","owner_id","kind","resource_id",name="uq_family_share"),
        sa.CheckConstraint("kind IN ('memory', 'task', 'event', 'inventory')",name="ck_family_share_kind"))
    op.create_index("ix_family_shares_space_id","family_shares",["space_id"])
    op.create_index("ix_family_shares_owner_id","family_shares",["owner_id"])
    op.create_table("family_items",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("space_id",sa.String(36),sa.ForeignKey("family_spaces.id",ondelete="CASCADE"),nullable=False),
        sa.Column("created_by",sa.String(36),sa.ForeignKey("users.id",ondelete="SET NULL")),
        sa.Column("kind",sa.String(12),nullable=False),
        sa.Column("title",sa.String(240),nullable=False),
        sa.Column("notes",sa.Text(),nullable=False),
        sa.Column("starts_at",sa.DateTime(timezone=True)),
        sa.Column("ends_at",sa.DateTime(timezone=True)),
        sa.Column("location",sa.String(500),nullable=False),
        sa.Column("status",sa.String(12),nullable=False),
        sa.Column("revision",sa.Integer(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("kind IN ('note', 'task', 'event', 'inventory')",name="ck_family_item_kind"),
        sa.CheckConstraint("status IN ('open', 'done')",name="ck_family_item_status"))
    op.create_index("ix_family_items_space","family_items",["space_id","created_at"])


def downgrade():
    op.drop_table("family_items")
    op.drop_table("family_shares")
    op.drop_table("family_memberships")
    op.drop_table("family_spaces")
