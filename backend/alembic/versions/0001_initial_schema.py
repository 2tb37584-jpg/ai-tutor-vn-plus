"""Initial application schema baseline.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial_schema"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "skills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("subject", sa.String(length=80), nullable=False),
        sa.Column("grade_min", sa.Integer(), nullable=True),
        sa.Column("grade_max", sa.Integer(), nullable=True),
        sa.Column("prerequisite_codes", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_skills_code", "skills", ["code"], unique=True)

    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=True),
        sa.Column("preferred_language", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_students_owner_id", "students", ["owner_id"], unique=False)

    op.create_table(
        "mastery",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("skill_code", sa.String(length=120), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("exposures", sa.Integer(), nullable=False),
        sa.Column("correct_streak", sa.Integer(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", "skill_code", name="uq_mastery_student_skill"),
    )
    op.create_index("ix_mastery_skill_code", "mastery", ["skill_code"], unique=False)
    op.create_index("ix_mastery_student_id", "mastery", ["student_id"], unique=False)

    op.create_table(
        "tutor_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("normalized_problem", sa.Text(), nullable=False),
        sa.Column("primary_skill", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tutor_sessions_student_id", "tutor_sessions", ["student_id"], unique=False)

    op.create_table(
        "tutor_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["tutor_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tutor_messages_session_id", "tutor_messages", ["session_id"], unique=False)

    op.create_table(
        "attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("skill_code", sa.String(length=120), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("hint_count", sa.Integer(), nullable=False),
        sa.Column("misconception", sa.String(length=240), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["tutor_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attempts_skill_code", "attempts", ["skill_code"], unique=False)
    op.create_index("ix_attempts_student_id", "attempts", ["student_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_attempts_student_id", table_name="attempts")
    op.drop_index("ix_attempts_skill_code", table_name="attempts")
    op.drop_table("attempts")
    op.drop_index("ix_tutor_messages_session_id", table_name="tutor_messages")
    op.drop_table("tutor_messages")
    op.drop_index("ix_tutor_sessions_student_id", table_name="tutor_sessions")
    op.drop_table("tutor_sessions")
    op.drop_index("ix_mastery_student_id", table_name="mastery")
    op.drop_index("ix_mastery_skill_code", table_name="mastery")
    op.drop_table("mastery")
    op.drop_index("ix_students_owner_id", table_name="students")
    op.drop_table("students")
    op.drop_index("ix_skills_code", table_name="skills")
    op.drop_table("skills")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
