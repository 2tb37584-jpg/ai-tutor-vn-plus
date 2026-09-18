"""Add persisted tutor session state.

Revision ID: 0002_tutor_session_state
Revises: 0001_initial_schema
Create Date: 2026-09-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_tutor_session_state"
down_revision: Union[str, Sequence[str], None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tutor_sessions",
        sa.Column(
            "current_state",
            sa.String(length=32),
            nullable=True,
            server_default="ask_attempt",
        ),
    )
    op.execute("UPDATE tutor_sessions SET current_state = 'ask_attempt' WHERE current_state IS NULL")
    op.alter_column(
        "tutor_sessions",
        "current_state",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("tutor_sessions", "current_state")
