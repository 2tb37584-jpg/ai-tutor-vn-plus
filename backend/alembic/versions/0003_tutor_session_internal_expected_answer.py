"""Add internal expected-answer storage to tutor sessions.

Revision ID: 0003_internal_expected_answer
Revises: 0002_tutor_session_state
Create Date: 2026-09-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_internal_expected_answer"
down_revision: Union[str, Sequence[str], None] = "0002_tutor_session_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tutor_sessions",
        sa.Column(
            "internal_expected_answer",
            sa.Text(),
            nullable=True,
            server_default="",
        ),
    )
    op.execute("UPDATE tutor_sessions SET internal_expected_answer = '' WHERE internal_expected_answer IS NULL")
    op.alter_column(
        "tutor_sessions",
        "internal_expected_answer",
        existing_type=sa.Text(),
        nullable=False,
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("tutor_sessions", "internal_expected_answer")
