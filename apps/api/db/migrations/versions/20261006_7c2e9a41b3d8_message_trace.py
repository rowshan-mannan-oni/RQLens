"""message trace

Revision ID: 7c2e9a41b3d8
Revises: 41fb0c00cbdd
Create Date: 2026-10-06 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c2e9a41b3d8"
down_revision: str | None = "41fb0c00cbdd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages", sa.Column("trace_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("messages", "trace_json")
