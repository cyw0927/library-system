"""Revocable login sessions; existing local reading records are left untouched."""
from alembic import op
import sqlalchemy as sa

revision = "0009_accounts"
down_revision = "0008_embeddings"
branch_labels = depends_on = None


def upgrade():
    op.create_table("accounts",
        sa.Column("id", sa.String(100), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("role", sa.String(16), server_default="reader", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'reader')", name=op.f("ck_accounts_valid_account_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.UniqueConstraint("username", name=op.f("uq_accounts_username")),
    )
    op.create_table("login_sessions",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["accounts.id"], ondelete="CASCADE", name=op.f("fk_login_sessions_user_id_accounts")),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_login_sessions")),
    )
    op.create_index("ix_login_sessions_user_id", "login_sessions", ["user_id"])
    op.create_index("ix_login_sessions_expires_at", "login_sessions", ["expires_at"])


def downgrade():
    op.drop_table("login_sessions")
    op.drop_table("accounts")
