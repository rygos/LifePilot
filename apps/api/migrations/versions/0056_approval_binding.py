from alembic import op
import sqlalchemy as sa

revision = "0056_approval_binding"
down_revision = "0055_tenant_integrity"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("approval_requests",sa.Column("resource_version",sa.String(64),nullable=True))
    op.add_column("approval_requests",sa.Column("payload",sa.JSON(),nullable=True))
    # Never silently upgrade a legacy approval into permission to delete today's data.
    op.execute("UPDATE approval_requests SET status='rejected', decided_at=CURRENT_TIMESTAMP WHERE status='pending'")


def downgrade():
    op.drop_column("approval_requests","payload")
    op.drop_column("approval_requests","resource_version")
