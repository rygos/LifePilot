from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("users", sa.Column("id", sa.String(36), primary_key=True), sa.Column("username", sa.String(120), nullable=False), sa.Column("password_hash", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_table("people", sa.Column("id", sa.String(36), primary_key=True), sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("first_name", sa.String(120), nullable=False), sa.Column("last_name", sa.String(120), nullable=False), sa.Column("nickname", sa.String(120)), sa.Column("birthday", sa.String(10)), sa.Column("email", sa.String(320)), sa.Column("phone", sa.String(80)), sa.Column("notes", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_people_owner_id", "people", ["owner_id"])
    op.create_table("memories", sa.Column("id", sa.String(36), primary_key=True), sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="SET NULL")), sa.Column("title", sa.String(240), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("source", sa.String(40), nullable=False), sa.Column("occurred_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_memories_owner_id", "memories", ["owner_id"])
    op.create_index("ix_memories_person_id", "memories", ["person_id"])
    op.create_table("tasks", sa.Column("id", sa.String(36), primary_key=True), sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="SET NULL")), sa.Column("title", sa.String(240), nullable=False), sa.Column("description", sa.Text(), nullable=False), sa.Column("due_at", sa.DateTime(timezone=True)), sa.Column("priority", sa.Integer(), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_tasks_owner_id", "tasks", ["owner_id"])
    op.create_index("ix_tasks_person_id", "tasks", ["person_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_table("relationships", sa.Column("id", sa.String(36), primary_key=True), sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("source_person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="CASCADE"), nullable=False), sa.Column("target_person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="CASCADE"), nullable=False), sa.Column("relationship_type", sa.String(100), nullable=False), sa.Column("valid_from", sa.DateTime(timezone=True)), sa.Column("valid_until", sa.DateTime(timezone=True)), sa.Column("source_memory_id", sa.String(36), sa.ForeignKey("memories.id", ondelete="SET NULL")), sa.Column("confirmed", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for name, column in [("owner_id", "owner_id"), ("source_person_id", "source_person_id"), ("target_person_id", "target_person_id")]:
        op.create_index(f"ix_relationships_{name}", "relationships", [column])

def downgrade():
    op.drop_table("relationships")
    op.drop_table("tasks")
    op.drop_table("memories")
    op.drop_table("people")
    op.drop_table("users")
