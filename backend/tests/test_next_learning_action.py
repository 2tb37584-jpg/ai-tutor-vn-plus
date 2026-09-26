from datetime import datetime

import pytest

from app.models import Mastery
from app.schemas.tutor import TutorState
from app.services import next_learning_action
from app.services.question_bank import QuestionBankItem
from app.services.question_recommender import MasterySnapshot


class ScalarResult:
    def __init__(self, rows: list[Mastery]) -> None:
        self.rows = rows

    def all(self) -> list[Mastery]:
        return self.rows


class ExplodingIterable:
    def __iter__(self):
        raise AssertionError("exclusions must not be consumed")


class FakeDatabase:
    def __init__(
        self,
        rows: list[Mastery] | None = None,
        pending: list[Mastery] | None = None,
    ) -> None:
        self.rows = rows or []
        self.pending = pending or []
        self.flush_calls = 0
        self.commit_calls = 0
        self.scalars_calls = 0
        self.last_statement: object | None = None

    def flush(self) -> None:
        self.flush_calls += 1
        self.rows.extend(self.pending)
        self.pending.clear()

    def scalars(self, statement: object) -> ScalarResult:
        self.scalars_calls += 1
        self.last_statement = statement
        student_id = next(iter(statement.compile().params.values()))
        return ScalarResult([row for row in self.rows if row.student_id == student_id])

    def commit(self) -> None:
        self.commit_calls += 1


def mastery(
    *,
    student_id: int,
    skill_code: str,
    probability: float,
    exposures: int,
    last_seen_at: datetime | None,
) -> Mastery:
    return Mastery(
        student_id=student_id,
        skill_code=skill_code,
        probability=probability,
        exposures=exposures,
        last_seen_at=last_seen_at,
    )


def question() -> QuestionBankItem:
    return QuestionBankItem(
        id="g8alg.linear-equation.001",
        skill_code="algebra.linear_equation",
        problem_text="Solve x + 5 = 12.",
        verification_reference="x+5=12",
        expected_answer="7",
        verification_family="linear_equation",
        difficulty=1,
    )


@pytest.mark.parametrize("state", [TutorState.ASK_ATTEMPT, TutorState.TRANSFER])
def test_non_complete_returns_none_without_query_or_recommendation(
    monkeypatch: pytest.MonkeyPatch,
    state: TutorState,
) -> None:
    db = FakeDatabase()
    monkeypatch.setattr(
        next_learning_action,
        "recommend_next_question",
        lambda **_kwargs: pytest.fail("non-COMPLETE must not recommend"),
    )

    result = next_learning_action.recommend_next_learning_question(
        db,
        student_id=7,
        tutor_state=state,
        now=datetime(2026, 1, 1),
        excluded_question_ids=ExplodingIterable(),
    )

    assert result is None
    assert db.flush_calls == 0
    assert db.scalars_calls == 0


def test_complete_maps_student_mastery_forwards_now_and_returns_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_at = datetime(2025, 12, 31)
    rows = [
        mastery(
            student_id=7,
            skill_code="algebra.linear_equation",
            probability=0.62,
            exposures=3,
            last_seen_at=seen_at,
        ),
        mastery(
            student_id=9,
            skill_code="algebra.factorization",
            probability=0.91,
            exposures=8,
            last_seen_at=seen_at,
        ),
    ]
    db = FakeDatabase(rows=rows)
    selected = question()
    fixed_now = datetime(2026, 1, 2, 3, 4, 5)
    calls: list[tuple[tuple[MasterySnapshot, ...], datetime, object]] = []

    def recommend(*, mastery_snapshots, now, excluded_question_ids):
        calls.append((tuple(mastery_snapshots), now, excluded_question_ids))
        return selected

    monkeypatch.setattr(next_learning_action, "recommend_next_question", recommend)

    result = next_learning_action.recommend_next_learning_question(
        db,
        student_id=7,
        tutor_state=TutorState.COMPLETE,
        now=fixed_now,
    )

    assert result is selected
    assert db.flush_calls == 1
    assert db.commit_calls == 0
    assert db.scalars_calls == 1
    assert db.last_statement is not None
    assert 7 in db.last_statement.compile().params.values()
    assert calls == [
        (
            (
                MasterySnapshot(
                    skill_code="algebra.linear_equation",
                    probability=0.62,
                    exposures=3,
                    last_seen_at=seen_at,
                ),
            ),
            fixed_now,
            (),
        )
    ]


def test_complete_forwards_exact_exclusion_object_and_calls_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeDatabase()
    excluded = ("pre-1", "post-1")
    selected = question()
    calls: list[object] = []

    def recommend(*, mastery_snapshots, now, excluded_question_ids):
        calls.append(excluded_question_ids)
        return selected

    monkeypatch.setattr(next_learning_action, "recommend_next_question", recommend)

    result = next_learning_action.recommend_next_learning_question(
        db,
        student_id=7,
        tutor_state=TutorState.COMPLETE,
        now=datetime(2026, 1, 2),
        excluded_question_ids=excluded,
    )

    assert result is selected
    assert calls == [excluded]
    assert calls[0] is excluded


def test_pending_mastery_is_visible_before_recommendation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = mastery(
        student_id=7,
        skill_code="algebra.linear_equation",
        probability=0.7,
        exposures=1,
        last_seen_at=None,
    )
    db = FakeDatabase(pending=[pending])
    observed: list[tuple[MasterySnapshot, ...]] = []
    monkeypatch.setattr(
        next_learning_action,
        "recommend_next_question",
        lambda *, mastery_snapshots, now, excluded_question_ids: observed.append(
            tuple(mastery_snapshots)
        )
        or question(),
    )

    next_learning_action.recommend_next_learning_question(
        db,
        student_id=7,
        tutor_state=TutorState.COMPLETE,
        now=datetime(2026, 1, 2),
    )

    assert observed == [
        (
            MasterySnapshot(
                skill_code="algebra.linear_equation",
                probability=0.7,
                exposures=1,
                last_seen_at=None,
            ),
        )
    ]


def test_exact_no_eligible_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDatabase()
    monkeypatch.setattr(
        next_learning_action,
        "recommend_next_question",
        lambda **_kwargs: (_ for _ in ()).throw(
            ValueError("no eligible question-bank skills")
        ),
    )

    assert (
        next_learning_action.recommend_next_learning_question(
            db,
            student_id=7,
            tutor_state=TutorState.COMPLETE,
            now=datetime(2026, 1, 2),
        )
        is None
    )


def test_unrelated_value_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDatabase()

    def raise_unrelated_error(**_kwargs):
        raise ValueError("invalid mastery snapshot")

    monkeypatch.setattr(next_learning_action, "recommend_next_question", raise_unrelated_error)

    with pytest.raises(ValueError, match="invalid mastery snapshot"):
        next_learning_action.recommend_next_learning_question(
            db,
            student_id=7,
            tutor_state=TutorState.COMPLETE,
            now=datetime(2026, 1, 2),
        )


def test_exclusion_validation_value_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeDatabase()

    def raise_exclusion_error(**_kwargs):
        raise ValueError("excluded question IDs must be non-empty strings")

    monkeypatch.setattr(
        next_learning_action,
        "recommend_next_question",
        raise_exclusion_error,
    )

    with pytest.raises(
        ValueError,
        match="excluded question IDs must be non-empty strings",
    ):
        next_learning_action.recommend_next_learning_question(
            db,
            student_id=7,
            tutor_state=TutorState.COMPLETE,
            now=datetime(2026, 1, 2),
            excluded_question_ids=("",),
        )
