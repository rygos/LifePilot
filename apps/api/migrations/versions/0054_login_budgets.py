from alembic import op
import sqlalchemy as sa

revision = "0054_login_budgets"
down_revision = "0053_family_spaces"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("login_budgets",
        sa.Column("key",sa.String(80),primary_key=True),
        sa.Column("count",sa.Integer(),nullable=False),
        sa.Column("expires_at",sa.Integer(),nullable=False))
    op.create_index("ix_login_budgets_expires_at","login_budgets",["expires_at"])


def downgrade():
    op.drop_table("login_budgets")
