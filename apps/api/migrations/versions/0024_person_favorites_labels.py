from alembic import op
import sqlalchemy as sa


revision = "0024_person_favorites_labels"
down_revision = "0023_user_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("people", sa.Column("how_met", sa.Text(), server_default="", nullable=False))
    op.add_column("people", sa.Column("tags", sa.JSON(), server_default=sa.text("'[]'"), nullable=False))
    op.add_column("people", sa.Column("is_favorite", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column("people", "is_favorite")
    op.drop_column("people", "tags")
    op.drop_column("people", "how_met")
