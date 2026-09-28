from __future__ import annotations
from datetime import UTC, datetime
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    students: Mapped[list[Student]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Student(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(16), default="vi")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    owner: Mapped[User] = relationship(back_populates="students")
    masteries: Mapped[list[Mastery]] = relationship(back_populates="student", cascade="all, delete-orphan")


class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(80), default="math")
    grade_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grade_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prerequisite_codes: Mapped[str] = mapped_column(Text, default="")


class Mastery(Base):
    __tablename__ = "mastery"
    __table_args__ = (UniqueConstraint("student_id", "skill_code", name="uq_mastery_student_skill"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    skill_code: Mapped[str] = mapped_column(String(120), index=True)
    probability: Mapped[float] = mapped_column(Float, default=0.35)
    exposures: Mapped[int] = mapped_column(Integer, default=0)
    correct_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    student: Mapped[Student] = relationship(back_populates="masteries")


def _pilot_timestamp() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class PilotEnrollment(Base):
    __tablename__ = "pilot_enrollments"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('pre', 'intervention', 'post', 'complete')",
            name="ck_pilot_enrollments_phase",
        ),
        Index(
            "uq_pilot_enrollments_nonterminal_student",
            "student_id",
            unique=True,
            postgresql_where=text("phase <> 'complete'"),
            sqlite_where=text("phase <> 'complete'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    phase: Mapped[str] = mapped_column(String(32), nullable=False, default="pre")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_pilot_timestamp)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_pilot_timestamp,
        onupdate=_pilot_timestamp,
    )


class PilotSkillAssignment(Base):
    __tablename__ = "pilot_skill_assignments"
    __table_args__ = (
        UniqueConstraint(
            "pilot_enrollment_id",
            "skill_code",
            name="uq_pilot_skill_assignments_enrollment_skill",
        ),
        CheckConstraint(
            "pre_question_id <> learning_question_id"
            " AND pre_question_id <> post_question_id"
            " AND learning_question_id <> post_question_id",
            name="ck_pilot_skill_assignments_distinct_questions",
        ),
        CheckConstraint(
            "pre_verification_status IS NULL OR pre_verification_status IN "
            "('correct', 'incorrect', 'unsupported', 'indeterminate')",
            name="ck_pilot_skill_assignments_pre_status",
        ),
        CheckConstraint(
            "post_verification_status IS NULL OR post_verification_status IN "
            "('correct', 'incorrect', 'unsupported', 'indeterminate')",
            name="ck_pilot_skill_assignments_post_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pilot_enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("pilot_enrollments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    skill_code: Mapped[str] = mapped_column(String(120), nullable=False)
    pre_question_id: Mapped[str] = mapped_column(String(120), nullable=False)
    learning_question_id: Mapped[str] = mapped_column(String(120), nullable=False)
    post_question_id: Mapped[str] = mapped_column(String(120), nullable=False)
    pre_verification_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pre_submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    learning_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    post_verification_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    post_submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TutorSession(Base):
    __tablename__ = "tutor_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240), default="New tutoring session")
    normalized_problem: Mapped[str] = mapped_column(Text, default="")
    primary_skill: Mapped[str] = mapped_column(String(120), default="general")
    status: Mapped[str] = mapped_column(String(32), default="active")
    current_state: Mapped[str] = mapped_column(String(32), nullable=False, default="ask_attempt")
    internal_expected_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    verification_family: Mapped[str | None] = mapped_column(String(32), nullable=True)
    authored_question_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    transfer_question_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pilot_skill_assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("pilot_skill_assignments.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TutorMessage(Base):
    __tablename__ = "tutor_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("tutor_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(24))
    content: Mapped[str] = mapped_column(Text)
    reply_intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    response_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("tutor_sessions.id", ondelete="SET NULL"), nullable=True)
    skill_code: Mapped[str] = mapped_column(String(120), index=True)
    correct: Mapped[bool] = mapped_column(Boolean)
    hint_count: Mapped[int] = mapped_column(Integer, default=0)
    misconception: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
