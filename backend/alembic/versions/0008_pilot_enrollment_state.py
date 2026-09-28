"""Persist Phase 3 pilot enrollment and frozen assignment state."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_pilot_enrollment_state"
down_revision: Union[str, Sequence[str], None] = "0007_tutor_authored_question_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PHASE_CHECK = "ck_pilot_enrollments_phase"
_NONTERMINAL_INDEX = "uq_pilot_enrollments_nonterminal_student"
_ASSIGNMENT_DISTINCT_CHECK = "ck_pilot_skill_assignments_distinct_questions"
_PRE_STATUS_CHECK = "ck_pilot_skill_assignments_pre_status"
_POST_STATUS_CHECK = "ck_pilot_skill_assignments_post_status"
_ASSIGNMENT_SKILL_UNIQUE = "uq_pilot_skill_assignments_enrollment_skill"
_TUTOR_PROVENANCE_INDEX = "ix_tutor_sessions_pilot_skill_assignment_id"


def upgrade() -> None:
    op.create_table(
        "pilot_enrollments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "phase IN ('pre', 'intervention', 'post', 'complete')",
            name=_PHASE_CHECK,
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(
        "ix_pilot_enrollments_student_id",
        "pilot_enrollments",
        ["student_id"],
        unique=False,
    )
    op.create_index(
        _NONTERMINAL_INDEX,
        "pilot_enrollments",
        ["student_id"],
        unique=True,
        postgresql_where=sa.text("phase <> 'complete'"),
        sqlite_where=sa.text("phase <> 'complete'"),
    )

    op.create_table(
        "pilot_skill_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pilot_enrollment_id", sa.Integer(), nullable=False),
        sa.Column("skill_code", sa.String(length=120), nullable=False),
        sa.Column("pre_question_id", sa.String(length=120), nullable=False),
        sa.Column("learning_question_id", sa.String(length=120), nullable=False),
        sa.Column("post_question_id", sa.String(length=120), nullable=False),
        sa.Column("pre_verification_status", sa.String(length=32), nullable=True),
        sa.Column("pre_submitted_at", sa.DateTime(), nullable=True),
        sa.Column("learning_completed_at", sa.DateTime(), nullable=True),
        sa.Column("post_verification_status", sa.String(length=32), nullable=True),
        sa.Column("post_submitted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "pre_question_id <> learning_question_id"
            " AND pre_question_id <> post_question_id"
            " AND learning_question_id <> post_question_id",
            name=_ASSIGNMENT_DISTINCT_CHECK,
        ),
        sa.CheckConstraint(
            "pre_verification_status IS NULL OR pre_verification_status IN "
            "('correct', 'incorrect', 'unsupported', 'indeterminate')",
            name=_PRE_STATUS_CHECK,
        ),
        sa.CheckConstraint(
            "post_verification_status IS NULL OR post_verification_status IN "
            "('correct', 'incorrect', 'unsupported', 'indeterminate')",
            name=_POST_STATUS_CHECK,
        ),
        sa.ForeignKeyConstraint(
            ["pilot_enrollment_id"],
            ["pilot_enrollments.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "pilot_enrollment_id",
            "skill_code",
            name=_ASSIGNMENT_SKILL_UNIQUE,
        ),
    )
    op.create_index(
        "ix_pilot_skill_assignments_pilot_enrollment_id",
        "pilot_skill_assignments",
        ["pilot_enrollment_id"],
        unique=False,
    )

    with op.batch_alter_table("tutor_sessions", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column("pilot_skill_assignment_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_tutor_sessions_pilot_skill_assignment_id",
            "pilot_skill_assignments",
            ["pilot_skill_assignment_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_index(
        _TUTOR_PROVENANCE_INDEX,
        "tutor_sessions",
        ["pilot_skill_assignment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(_TUTOR_PROVENANCE_INDEX, table_name="tutor_sessions")
    with op.batch_alter_table("tutor_sessions", recreate="always") as batch_op:
        batch_op.drop_constraint(
            "fk_tutor_sessions_pilot_skill_assignment_id",
            type_="foreignkey",
        )
        batch_op.drop_column("pilot_skill_assignment_id")

    op.drop_index(
        "ix_pilot_skill_assignments_pilot_enrollment_id",
        table_name="pilot_skill_assignments",
    )
    op.drop_table("pilot_skill_assignments")
    op.drop_index(_NONTERMINAL_INDEX, table_name="pilot_enrollments")
    op.drop_index("ix_pilot_enrollments_student_id", table_name="pilot_enrollments")
    op.drop_table("pilot_enrollments")
