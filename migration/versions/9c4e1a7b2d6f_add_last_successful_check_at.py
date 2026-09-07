"""add last successful check timestamp

Revision ID: 9c4e1a7b2d6f
Revises: ea1271258fac
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c4e1a7b2d6f"
down_revision: str | Sequence[str] | None = "ea1271258fac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column(
            "last_successful_check_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("items", "last_successful_check_at")
