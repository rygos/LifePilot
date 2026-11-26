from alembic import op

from lifepilot.tenant_integrity_v1 import install, preflight, uninstall

revision = "0055_tenant_integrity"
down_revision = "0054_login_budgets"
branch_labels = None
depends_on = None


def upgrade():
    connection=op.get_bind()
    # Block concurrent writes between the legacy check and trigger installation.
    if connection.dialect.name=="postgresql":
        from lifepilot.tenant_integrity_v1 import OWNED_TABLES
        connection.exec_driver_sql("LOCK TABLE "+", ".join(sorted(OWNED_TABLES))+" IN SHARE ROW EXCLUSIVE MODE")
    preflight(connection)
    install(connection)


def downgrade():
    uninstall(op.get_bind())
