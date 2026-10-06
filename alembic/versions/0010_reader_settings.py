"""Persist reader preferences without changing book content or reading records."""
from alembic import op
import sqlalchemy as sa

revision = "0010_reader_settings"
down_revision = "0009_accounts"
branch_labels = depends_on = None


def upgrade():
    op.create_table("reader_settings",
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_reader_settings")),
    )


def downgrade():
    op.drop_table("reader_settings")
