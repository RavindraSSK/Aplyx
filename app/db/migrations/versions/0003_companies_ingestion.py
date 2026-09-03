"""companies + ingestion_runs; job provenance/lifecycle/salary columns

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False, unique=True),
        sa.Column("ats_provider", sa.String(32), nullable=True),
        sa.Column("ats_slug", sa.String(255), nullable=True),
        sa.Column("careers_url", sa.String(1024), nullable=False, server_default=""),
        sa.Column("domain", sa.String(255), nullable=False, server_default=""),
        sa.Column("category", sa.String(64), nullable=False, server_default=""),
        sa.Column("hq_location", sa.String(255), nullable=False, server_default=""),
        sa.Column("headcount_band", sa.String(16), nullable=False, server_default=""),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tier_seed", sa.Integer(), nullable=True),
        sa.Column("tier", sa.Integer(), nullable=True),
        sa.Column("tier_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("tier_confidence", sa.Float(), nullable=True),
        sa.Column("tier_override", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_fetch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fetch_status", sa.String(16), nullable=False, server_default="never"),
        sa.Column("last_fetch_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_fetch_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_companies", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_companies", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("aggregators_done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sources", sa.JSON(), nullable=False),
    )
    with op.batch_alter_table("jobs") as b:
        b.add_column(sa.Column("source_name", sa.String(255), nullable=False, server_default=""))
        b.add_column(sa.Column("company_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("status", sa.String(16), nullable=False, server_default="open"))
        b.add_column(sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("dedupe_key", sa.String(40), nullable=True))
        b.add_column(sa.Column("duplicate_of", sa.Integer(), nullable=True))
        b.add_column(sa.Column("employment_type", sa.String(24), nullable=True))
        b.add_column(sa.Column("salary_min", sa.Float(), nullable=True))
        b.add_column(sa.Column("salary_max", sa.Float(), nullable=True))
        b.add_column(sa.Column("salary_currency", sa.String(8), nullable=True))
        b.add_column(sa.Column("salary_period", sa.String(8), nullable=True))
        b.add_column(sa.Column("application_deadline", sa.DateTime(timezone=True), nullable=True))
        b.create_foreign_key("fk_jobs_company_id_companies", "companies", ["company_id"], ["id"])
        b.create_foreign_key("fk_jobs_duplicate_of_jobs", "jobs", ["duplicate_of"], ["id"])
        b.create_index("ix_jobs_company_id", ["company_id"])
        b.create_index("ix_jobs_status", ["status"])
        b.create_index("ix_jobs_dedupe_key", ["dedupe_key"])
    # Existing rows: first/last seen = created_at (the only honest value we have)
    op.execute("UPDATE jobs SET first_seen_at = created_at, last_seen_at = updated_at WHERE first_seen_at IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("jobs") as b:
        b.drop_index("ix_jobs_dedupe_key")
        b.drop_index("ix_jobs_status")
        b.drop_index("ix_jobs_company_id")
        b.drop_constraint("fk_jobs_duplicate_of_jobs", type_="foreignkey")
        b.drop_constraint("fk_jobs_company_id_companies", type_="foreignkey")
        for col in ("application_deadline", "salary_period", "salary_currency", "salary_max", "salary_min",
                    "employment_type", "duplicate_of", "dedupe_key", "closed_at", "last_seen_at",
                    "first_seen_at", "status", "company_id", "source_name"):
            b.drop_column(col)
    op.drop_table("ingestion_runs")
    op.drop_table("companies")
