"""add users table - corporate Active Directory sign-in

Accounts are auto-provisioned on first successful AD login, so this table
starts empty and fills itself; there is no data migration to perform. The
directory profile columns (department in particular) are refreshed from AD on
every login and are what scope offer visibility.

Deliberately NOT unique on email: the directory reports an absent attribute as
an empty value, so several accounts can legitimately carry ''. A unique
constraint would let the first such account provision and then permanently
block every later one with an integrity error at login.

Revision ID: 0011_users_auth
Revises: 0010_payment_schedule_scope
Create Date: 2026-09-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# NOTE: the predecessor's revision id is "0010_payment_schedule_scope" even
# though its FILE is named 0010_payment_schedule_scope_items.py - the id is
# what alembic resolves, and using the filename here fails with
# "Can't locate revision identified by ...".
revision: str = "0011_users_auth"
down_revision: Union[str, None] = "0010_payment_schedule_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False, server_default=""),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("auth_source", sa.Text(), nullable=False, server_default="ldap"),
        sa.Column("role", sa.Text(), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("display_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("department", sa.Text(), nullable=False, server_default=""),
        sa.Column("company", sa.Text(), nullable=False, server_default=""),
        sa.Column("job_title", sa.Text(), nullable=False, server_default=""),
        sa.Column("office", sa.Text(), nullable=False, server_default=""),
        sa.Column("city", sa.Text(), nullable=False, server_default=""),
        sa.Column("ldap_groups", sa.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
        sa.CheckConstraint("auth_source IN ('ldap', 'local')", name="ck_users_auth_source"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Unique: the login identifier. Everything else is a lookup index.
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)
    op.create_index(op.f("ix_users_department"), "users", ["department"], unique=False)
    op.create_index(op.f("ix_users_company"), "users", ["company"], unique=False)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)
    op.create_index(op.f("ix_users_auth_source"), "users", ["auth_source"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_auth_source"), table_name="users")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_index(op.f("ix_users_company"), table_name="users")
    op.drop_index(op.f("ix_users_department"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_table("users")
