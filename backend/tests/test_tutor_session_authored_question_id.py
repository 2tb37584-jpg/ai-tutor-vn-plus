import importlib.util
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, Integer, MetaData, create_engine, inspect
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models import Student, TutorSession, User


_MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "0007_tutor_authored_question_id.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("m07_tutor_authored_question_id", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_authored_question_id_round_trips_nullable_and_non_null_values_independently() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(email="parent@example.com", password_hash="hash")
        session.add(user)
        session.flush()

        student = Student(owner_id=user.id, display_name="Student", grade=8)
        session.add(student)
        session.flush()

        tutor_session = TutorSession(student_id=student.id)
        session.add(tutor_session)
        session.commit()
        session.expire_all()

        loaded = session.get(TutorSession, tutor_session.id)
        assert loaded is not None
        assert loaded.authored_question_id is None
        assert loaded.transfer_question_id is None

        loaded.authored_question_id = "g8alg.factorization.001"
        loaded.transfer_question_id = "g8alg.linear_equation.001"
        session.commit()
        session.expire_all()

        reloaded = session.get(TutorSession, tutor_session.id)
        assert reloaded is not None
        assert reloaded.authored_question_id == "g8alg.factorization.001"
        assert reloaded.transfer_question_id == "g8alg.linear_equation.001"


def test_authored_question_id_migration_adds_and_removes_only_nullable_column() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    from sqlalchemy import Table

    Table(
        "tutor_sessions",
        metadata,
        Column("id", Integer, primary_key=True),
    )
    metadata.create_all(engine)
    migration = _load_migration()

    with engine.begin() as connection:
        assert [column["name"] for column in inspect(connection).get_columns("tutor_sessions")] == ["id"]

        migration_context = MigrationContext.configure(connection)
        with Operations.context(migration_context):
            migration.upgrade()

        columns = {
            column["name"]: column
            for column in inspect(connection).get_columns("tutor_sessions")
        }
        assert set(columns) == {"id", "authored_question_id"}
        assert columns["authored_question_id"]["nullable"] is True
        assert columns["authored_question_id"]["type"].length == 120

        migration_context = MigrationContext.configure(connection)
        with Operations.context(migration_context):
            migration.downgrade()

        assert [column["name"] for column in inspect(connection).get_columns("tutor_sessions")] == ["id"]
