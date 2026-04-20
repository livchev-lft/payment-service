"""webhook delivery fields on payments

Revision ID: 0002_webhook_delivery
Revises: 0001_initial
Create Date: 2026-04-19 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_webhook_delivery"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column(
            "webhook_delivery_status",
            sa.String(16),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "payments",
        sa.Column("webhook_delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("webhook_failure_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payments", "webhook_failure_reason")
    op.drop_column("payments", "webhook_delivered_at")
    op.drop_column("payments", "webhook_delivery_status")
