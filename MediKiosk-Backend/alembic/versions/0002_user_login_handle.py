"""add users.login_handle for staff/kiosk auth

Revision ID: 0002_login_handle
Revises: 0001_initial
Create Date: 2026-09-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_login_handle"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("login_handle", sa.String(length=128), nullable=True))
    op.create_unique_constraint("uq_users_login_handle", "users", ["login_handle"])


def downgrade() -> None:
    op.drop_constraint("uq_users_login_handle", "users", type_="unique")
    op.drop_column("users", "login_handle")
