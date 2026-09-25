"""Persist authored question identity on tutor sessions.

Revision ID: 0007_tutor_authored_question_id
Revises: 0006_tutor_transfer_question_id
Create Date: 2026-09-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_tutor_authored_question_id"
down_revision: Union[str, Sequence[str], None] = "0006_tutor_transfer_question_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tutor_sessions",
        sa.Column("authored_question_id", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tutor_sessions", "authored_question_id")
