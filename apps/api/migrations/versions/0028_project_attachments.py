from alembic import op


revision = "0028_project_attachments"
down_revision = "0027_resource_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("attachments") as batch_op:
        batch_op.drop_constraint("ck_attachments_resource_type", type_="check")
        batch_op.create_check_constraint(
            "ck_attachments_resource_type",
            "resource_type IN ('person', 'memory', 'conversation', 'event', 'project')",
        )


def downgrade() -> None:
    with op.batch_alter_table("attachments") as batch_op:
        batch_op.drop_constraint("ck_attachments_resource_type", type_="check")
        batch_op.create_check_constraint(
            "ck_attachments_resource_type",
            "resource_type IN ('person', 'memory', 'conversation', 'event')",
        )
