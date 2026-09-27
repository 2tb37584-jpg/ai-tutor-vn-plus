from datetime import datetime

import pytest

from app.schemas.tutor import TutorState
from app.services import pilot_learning_action
from app.services.pilot_assessment_assignment import PilotSkillAssignment
from app.services.question_bank import QuestionBankItem


NOW = datetime(2026, 9, 24, 12, 0, 0)


def _assignments() -> tuple[PilotSkillAssignment, ...]:
    return (
        PilotSkillAssignment(
            skill_code="skill.a",
            pre_question_id="a-pre",
            learning_question_id="a-learning",
            post_question_id="a-post",
        ),
        PilotSkillAssignment(
            skill_code="skill.b",
            pre_question_id="b-pre",
            learning_question_id="b-learning",
            post_question_id="b-post",
        ),
    )


def _question() -> QuestionBankItem:
    return QuestionBankItem(
        id="question-1",
        skill_code="skill.a",
        problem_text="problem",
        verification_reference="reference",
        expected_answer="answer",
        verification_family="numeric",
        difficulty=1,
    )


def test_complete_derives_reserved_pre_post_ids_and_forwards_exact_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = object()
    now = object()
    assignment_seeds: list[str] = []
    downstream_calls: list[dict[str, object]] = []
    selected = _question()

    def assign(*, assignment_seed: str):
        assignment_seeds.append(assignment_seed)
        return _assignments()

    def recommend(db_arg, *, student_id, tutor_state, now, excluded_question_ids):
        downstream_calls.append(
            {
                "db": db_arg,
                "student_id": student_id,
                "tutor_state": tutor_state,
                "now": now,
                "excluded_question_ids": excluded_question_ids,
            }
        )
        return selected

    monkeypatch.setattr(pilot_learning_action, "assign_pilot_items", assign)
    monkeypatch.setattr(
        pilot_learning_action,
        "recommend_next_learning_question",
        recommend,
    )

    result = pilot_learning_action.recommend_next_pilot_learning_question(
        db,
        student_id=7,
        tutor_state=TutorState.COMPLETE,
        now=now,
        assignment_seed="pilot-seed-a",
    )

    assert result is selected
    assert assignment_seeds == ["pilot-seed-a"]
    assert downstream_calls == [
        {
            "db": db,
            "student_id": 7,
            "tutor_state": TutorState.COMPLETE,
            "now": now,
            "excluded_question_ids": (
                "a-pre",
                "a-post",
                "b-pre",
                "b-post",
            ),
        }
    ]
    assert downstream_calls[0]["db"] is db
    assert downstream_calls[0]["now"] is now
    assert "a-learning" not in downstream_calls[0]["excluded_question_ids"]
    assert "b-learning" not in downstream_calls[0]["excluded_question_ids"]


def test_downstream_none_is_returned_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pilot_learning_action,
        "assign_pilot_items",
        lambda *, assignment_seed: _assignments(),
    )
    monkeypatch.setattr(
        pilot_learning_action,
        "recommend_next_learning_question",
        lambda *args, **kwargs: None,
    )

    result = pilot_learning_action.recommend_next_pilot_learning_question(
        object(),
        student_id=7,
        tutor_state=TutorState.COMPLETE,
        now=NOW,
        assignment_seed="pilot-seed-a",
    )

    assert result is None


@pytest.mark.parametrize("state", [TutorState.ASK_ATTEMPT, TutorState.TRANSFER])
def test_non_complete_short_circuits_before_assignment_or_downstream(
    monkeypatch: pytest.MonkeyPatch,
    state: TutorState,
) -> None:
    monkeypatch.setattr(
        pilot_learning_action,
        "assign_pilot_items",
        lambda **kwargs: pytest.fail("assignment must not be called"),
    )
    monkeypatch.setattr(
        pilot_learning_action,
        "recommend_next_learning_question",
        lambda *args, **kwargs: pytest.fail("downstream must not be called"),
    )

    result = pilot_learning_action.recommend_next_pilot_learning_question(
        object(),
        student_id=7,
        tutor_state=state,
        now=NOW,
        assignment_seed="",
    )

    assert result is None


def test_assignment_seed_error_propagates_without_downstream_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downstream_calls = 0

    def assign(*, assignment_seed: str):
        raise ValueError("assignment_seed must be a non-empty string")

    def recommend(*args, **kwargs):
        nonlocal downstream_calls
        downstream_calls += 1
        return None

    monkeypatch.setattr(pilot_learning_action, "assign_pilot_items", assign)
    monkeypatch.setattr(
        pilot_learning_action,
        "recommend_next_learning_question",
        recommend,
    )

    with pytest.raises(ValueError, match="^assignment_seed must be a non-empty string$"):
        pilot_learning_action.recommend_next_pilot_learning_question(
            object(),
            student_id=7,
            tutor_state=TutorState.COMPLETE,
            now=NOW,
            assignment_seed="",
        )

    assert downstream_calls == 0


def test_empty_assignments_forward_empty_exclusions(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[object] = []
    monkeypatch.setattr(
        pilot_learning_action,
        "assign_pilot_items",
        lambda *, assignment_seed: (),
    )

    def recommend(db_arg, *, excluded_question_ids, **kwargs):
        received.append(excluded_question_ids)
        return None

    monkeypatch.setattr(
        pilot_learning_action,
        "recommend_next_learning_question",
        recommend,
    )

    result = pilot_learning_action.recommend_next_pilot_learning_question(
        object(),
        student_id=7,
        tutor_state=TutorState.COMPLETE,
        now=NOW,
        assignment_seed="pilot-seed-a",
    )

    assert result is None
    assert received == [()]
