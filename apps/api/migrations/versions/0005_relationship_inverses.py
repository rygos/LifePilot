from alembic import op
import sqlalchemy as sa

revision = "0005_relationship_inverses"
down_revision = "0004_person_profiles"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("relationships") as batch:
        batch.add_column(sa.Column("inverse_relationship_type", sa.String(100), nullable=False, server_default="Beziehung zu"))

def downgrade():
    with op.batch_alter_table("relationships") as batch:
        batch.drop_column("inverse_relationship_type")
