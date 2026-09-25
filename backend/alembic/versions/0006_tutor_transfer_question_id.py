"""Persist authored transfer-question identity on tutor sessions.

Revision ID: 0006_tutor_transfer_question_id
Revises: 0005_tutor_verifier_family
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_tutor_transfer_question_id"
down_revision: Union[str, Sequence[str], None] = "0005_tutor_verifier_family"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tutor_sessions",
        sa.Column("transfer_question_id", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tutor_sessions", "transfer_question_id")
