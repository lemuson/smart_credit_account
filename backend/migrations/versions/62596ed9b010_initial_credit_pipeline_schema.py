"""initial credit pipeline schema

Revision ID: 62596ed9b010
Revises:
"""

import sqlalchemy as sa
from alembic import op

import app.database

revision = "62596ed9b010"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", app.database.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "credit_products",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("purposes", sa.JSON(), nullable=False),
        sa.Column("min_amount", app.database.FixedDecimal(2), nullable=False),
        sa.Column("max_amount", app.database.FixedDecimal(2), nullable=False),
        sa.Column("min_term_months", sa.Integer(), nullable=False),
        sa.Column("max_term_months", sa.Integer(), nullable=False),
        sa.Column("annual_rate", app.database.FixedDecimal(2), nullable=False),
        sa.Column("min_business_age_months", sa.Integer(), nullable=False),
        sa.Column("min_annual_revenue", app.database.FixedDecimal(2), nullable=False),
        sa.Column("max_debt_burden", app.database.FixedDecimal(4), nullable=False),
        sa.Column("collateral_required", sa.Boolean(), nullable=False),
        sa.Column("required_documents", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("demonstration_only", sa.Boolean(), nullable=False),
        sa.Column("created_at", app.database.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_products")),
    )
    op.create_table(
        "loans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=True),
        sa.Column("external_reference", sa.String(length=100), nullable=True),
        sa.Column("amount", app.database.FixedDecimal(2), nullable=False),
        sa.Column("outstanding_balance", app.database.FixedDecimal(2), nullable=False),
        sa.Column("monthly_payment", app.database.FixedDecimal(2), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("annual_rate", app.database.FixedDecimal(2), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("overdue_days", sa.Integer(), nullable=False),
        sa.Column("company_snapshot", sa.JSON(), nullable=False),
        sa.Column("financials_snapshot", sa.JSON(), nullable=False),
        sa.Column("demonstration_only", sa.Boolean(), nullable=False),
        sa.Column("created_at", app.database.UTCDateTime(), nullable=False),
        *(
            [
                sa.ForeignKeyConstraint(
                    ["application_id"],
                    ["applications.id"],
                    name=op.f("fk_loans_application_id_applications"),
                )
            ]
            if op.get_context().dialect.name == "sqlite"
            else []
        ),
        sa.ForeignKeyConstraint(["client_id"], ["users.id"], name=op.f("fk_loans_client_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_loans")),
        sa.UniqueConstraint("application_id", name=op.f("uq_loans_application_id")),
        sa.UniqueConstraint("external_reference", name=op.f("uq_loans_external_reference")),
    )
    with op.batch_alter_table("loans", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_loans_client_id"), ["client_id"], unique=False)

    op.create_table(
        "applications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("assigned_manager_id", sa.String(length=36), nullable=True),
        sa.Column("source_loan_id", sa.String(length=36), nullable=True),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("amount", app.database.FixedDecimal(2), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("company", sa.JSON(), nullable=False),
        sa.Column("financials", sa.JSON(), nullable=False),
        sa.Column("product_snapshot", sa.JSON(), nullable=False),
        sa.Column("data_revision", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("decision", sa.JSON(), nullable=True),
        sa.Column("offer", sa.JSON(), nullable=True),
        sa.Column("contract", sa.JSON(), nullable=True),
        sa.Column("signing_code_hash", sa.String(length=255), nullable=True),
        sa.Column("signing_expires_at", app.database.UTCDateTime(), nullable=True),
        sa.Column("signing_attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", app.database.UTCDateTime(), nullable=False),
        sa.Column("updated_at", app.database.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assigned_manager_id"],
            ["users.id"],
            name=op.f("fk_applications_assigned_manager_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["users.id"], name=op.f("fk_applications_client_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["credit_products.id"],
            name=op.f("fk_applications_product_id_credit_products"),
        ),
        sa.ForeignKeyConstraint(
            ["source_loan_id"], ["loans.id"], name=op.f("fk_applications_source_loan_id_loans")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_applications")),
    )
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_applications_client_id"), ["client_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_applications_status"), ["status"], unique=False)

    if op.get_context().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_loans_application_id_applications",
            "loans",
            "applications",
            ["application_id"],
            ["id"],
        )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", app.database.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_audit_events_actor_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_audit_events_application_id_applications"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    with op.batch_alter_table("audit_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_audit_events_application_id"), ["application_id"], unique=False
        )

    op.create_table(
        "check_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("data_revision", sa.Integer(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_at", app.database.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_check_runs_application_id_applications"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_check_runs")),
    )
    with op.batch_alter_table("check_runs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_check_runs_application_id"), ["application_id"], unique=False
        )

    op.create_table(
        "clarifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("manager_id", sa.String(length=36), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("required_fields", sa.JSON(), nullable=False),
        sa.Column("required_documents", sa.JSON(), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("responded_at", app.database.UTCDateTime(), nullable=True),
        sa.Column("created_at", app.database.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_clarifications_application_id_applications"),
        ),
        sa.ForeignKeyConstraint(
            ["manager_id"], ["users.id"], name=op.f("fk_clarifications_manager_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clarifications")),
    )
    with op.batch_alter_table("clarifications", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_clarifications_application_id"), ["application_id"], unique=False
        )

    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", app.database.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_documents_application_id_applications"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_documents_application_id"), ["application_id"], unique=False
        )

    op.create_table(
        "profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("company", sa.JSON(), nullable=False),
        sa.Column("financials", sa.JSON(), nullable=False),
        sa.Column("updated_at", app.database.UTCDateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_profiles_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profiles")),
        sa.UniqueConstraint("user_id", name=op.f("uq_profiles_user_id")),
    )


def downgrade():
    op.drop_table("profiles")
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_documents_application_id"))

    op.drop_table("documents")
    with op.batch_alter_table("clarifications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_clarifications_application_id"))

    op.drop_table("clarifications")
    with op.batch_alter_table("check_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_check_runs_application_id"))

    op.drop_table("check_runs")
    with op.batch_alter_table("audit_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_audit_events_application_id"))

    op.drop_table("audit_events")
    if op.get_context().dialect.name != "sqlite":
        op.drop_constraint("fk_loans_application_id_applications", "loans", type_="foreignkey")
    op.drop_table("applications")
    op.drop_table("loans")
    op.drop_table("credit_products")
    op.drop_table("users")
