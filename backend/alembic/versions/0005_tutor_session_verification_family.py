"""Add trusted verifier-family routing metadata to tutor sessions.

Revision ID: 0005_tutor_session_verification_family
Revises: 0004_tutor_message_reply_latency
Create Date: 2026-09-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_tutor_session_verification_family"
down_revision: Union[str, Sequence[str], None] = "0004_tutor_message_reply_latency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tutor_sessions",
        sa.Column("verification_family", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tutor_sessions", "verification_family")
