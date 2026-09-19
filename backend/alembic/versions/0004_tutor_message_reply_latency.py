"""Add reply intent and latency telemetry to tutor messages.

Revision ID: 0004_tutor_message_reply_latency
Revises: 0003_internal_expected_answer
Create Date: 2026-09-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_tutor_message_reply_latency"
down_revision: Union[str, Sequence[str], None] = "0003_internal_expected_answer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tutor_messages",
        sa.Column("reply_intent", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "tutor_messages",
        sa.Column("response_latency_ms", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tutor_messages", "response_latency_ms")
    op.drop_column("tutor_messages", "reply_intent")
