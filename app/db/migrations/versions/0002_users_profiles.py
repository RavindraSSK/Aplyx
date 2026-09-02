"""users, resume_files, candidate_profiles, llm_usage; user_id on per-user
tables; Postgres row-level security (fail closed) and pgvector when available.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-02

"""
import os

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

PER_USER_TABLES = ("applications", "tailored_resumes", "resume_files", "candidate_profiles", "llm_usage")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _pgvector_available() -> bool:
    if not _is_postgres():
        return False
    row = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
    ).first()
    return row is not None


def upgrade() -> None:
    bind = op.get_bind()

    if _pgvector_available():
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        from pgvector.sqlalchemy import Vector

        embedding_type = Vector()
    else:
        embedding_type = sa.JSON()

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    owner_email = os.environ.get("OWNER_EMAIL", "owner@local")
    bind.execute(
        sa.text(
            "INSERT INTO users (email, display_name, created_at) "
            "VALUES (:email, 'Owner', CURRENT_TIMESTAMP)"
        ),
        {"email": owner_email},
    )
    owner_id = bind.execute(sa.text("SELECT id FROM users WHERE email = :e"), {"e": owner_email}).scalar()

    # user_id on existing per-user tables: add nullable, backfill owner, make NOT NULL.
    for table in ("applications", "tailored_resumes"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        bind.execute(sa.text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"), {"uid": owner_id})
        with op.batch_alter_table(table) as batch:
            batch.alter_column("user_id", nullable=False)
            batch.create_foreign_key(f"fk_{table}_user_id_users", "users", ["user_id"], ["id"])
            batch.create_index(f"ix_{table}_user_id", ["user_id"])

    op.create_table(
        "resume_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "candidate_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("resume_file_id", sa.Integer(), sa.ForeignKey("resume_files.id"), nullable=True),
        sa.Column("parsed", sa.JSON(), nullable=False),
        sa.Column("overrides", sa.JSON(), nullable=False),
        sa.Column("effective", sa.JSON(), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("parser_model", sa.String(64), nullable=False),
        sa.Column("embedding", embedding_type, nullable=True),
        sa.Column("embedding_model", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_candidate_profiles_user_version", "candidate_profiles", ["user_id", "version"], unique=True
    )
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("feature", sa.String(64), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Row-level security: every per-user table only shows rows whose user_id
    # matches app.user_id (set per transaction by app/db/tenancy.py). FORCE
    # makes it apply to the table owner too, so a forgotten filter fails closed.
    if _is_postgres():
        for table in PER_USER_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {table}_tenant ON {table} "
                f"USING (user_id = NULLIF(current_setting('app.user_id', true), '')::int) "
                f"WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::int)"
            )


def downgrade() -> None:
    if _is_postgres():
        for table in PER_USER_TABLES:
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("llm_usage")
    op.drop_index("ix_candidate_profiles_user_version", table_name="candidate_profiles")
    op.drop_table("candidate_profiles")
    op.drop_table("resume_files")
    for table in ("applications", "tailored_resumes"):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_user_id")
            batch.drop_constraint(f"fk_{table}_user_id_users", type_="foreignkey")
            batch.drop_column("user_id")
    op.drop_table("users")
