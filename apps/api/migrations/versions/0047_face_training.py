from alembic import op
import sqlalchemy as sa

revision = "0047_face_training"
down_revision = "0046_fact_conflicts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "face_training_cards",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("photo_key", sa.String(80), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_review_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "person_id", name="uq_face_training_person"),
        sa.CheckConstraint("level BETWEEN 0 AND 7", name="ck_face_training_level"),
    )
    op.create_index("ix_face_training_cards_owner_id", "face_training_cards", ["owner_id"])
    op.create_index("ix_face_training_due", "face_training_cards", ["owner_id", "active", "due_at"])


def downgrade():
    op.drop_table("face_training_cards")
