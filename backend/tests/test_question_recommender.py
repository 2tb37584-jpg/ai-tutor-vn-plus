from datetime import datetime, timedelta, timezone

import pytest

from app.services.question_bank import QuestionBankItem
from app.services.question_recommender import MasterySnapshot, recommend_next_question
import app.services.question_recommender as recommender


NOW = datetime(2026, 9, 23, 12, 0, 0)


def _question(question_id: str, skill_code: str, difficulty: int) -> QuestionBankItem:
    return QuestionBankItem(
        id=question_id,
        skill_code=skill_code,
        problem_text="problem",
        verification_reference="1",
        expected_answer="1",
        verification_family="numeric",
        difficulty=difficulty,
    )


def _configure_policy(monkeypatch, questions, prerequisites=None, known_skills=None):
    prerequisites = prerequisites or {}
    known_skills = known_skills or {question.skill_code for question in questions}
    monkeypatch.setattr(recommender, "get_all_questions", lambda: tuple(questions))
    monkeypatch.setattr(
        recommender,
        "get_direct_prerequisites",
        lambda skill_code: tuple(prerequisites.get(skill_code, ())),
    )
    monkeypatch.setattr(
        recommender,
        "get_skill_definition",
        lambda skill_code: object() if skill_code in known_skills else None,
    )


def _snapshot(skill_code: str, probability: float, exposures: int, last_seen_at=NOW):
    return MasterySnapshot(skill_code, probability, exposures, last_seen_at)


def test_root_skill_is_eligible_when_dependent_is_blocked(monkeypatch):
    questions = [_question("root", "root", 1), _question("dependent", "dependent", 1)]
    _configure_policy(monkeypatch, questions, {"dependent": ("root",)})

    result = recommend_next_question(mastery_snapshots=(), now=NOW)

    assert result.id == "root"


@pytest.mark.parametrize(
    "prerequisite",
    [None, _snapshot("root", 0.80, 0), _snapshot("root", 0.79, 1)],
    ids=["missing", "zero_exposures", "below_threshold"],
)
def test_dependent_skill_is_blocked_until_prerequisite_is_mastered(monkeypatch, prerequisite):
    questions = [_question("dependent", "dependent", 1)]
    _configure_policy(
        monkeypatch,
        questions,
        {"dependent": ("root",)},
        {"root", "dependent"},
    )

    with pytest.raises(ValueError, match="no eligible"):
        recommend_next_question(
            mastery_snapshots=() if prerequisite is None else (prerequisite,), now=NOW
        )


def test_prerequisite_at_threshold_unlocks_dependent_skill(monkeypatch):
    questions = [_question("dependent", "dependent", 1)]
    _configure_policy(
        monkeypatch,
        questions,
        {"dependent": ("root",)},
        {"root", "dependent"},
    )

    result = recommend_next_question(
        mastery_snapshots=(_snapshot("root", 0.80, 1),), now=NOW
    )

    assert result.id == "dependent"


def test_seen_due_outranks_unseen(monkeypatch):
    questions = [_question("unseen", "unseen", 1), _question("due", "due", 1)]
    _configure_policy(monkeypatch, questions)

    result = recommend_next_question(
        mastery_snapshots=(_snapshot("due", 0.90, 1, NOW - timedelta(days=8)),),
        now=NOW,
    )

    assert result.id == "due"


def test_unseen_outranks_seen_not_due(monkeypatch):
    questions = [_question("unseen", "unseen", 1), _question("recent", "recent", 1)]
    _configure_policy(monkeypatch, questions)

    result = recommend_next_question(
        mastery_snapshots=(_snapshot("recent", 0.10, 1, NOW),), now=NOW
    )

    assert result.id == "unseen"


def test_lower_probability_wins_within_priority_class(monkeypatch):
    questions = [_question("higher", "higher", 1), _question("lower", "lower", 1)]
    _configure_policy(monkeypatch, questions)

    result = recommend_next_question(
        mastery_snapshots=(
            _snapshot("higher", 0.40, 1, NOW - timedelta(days=1)),
            _snapshot("lower", 0.20, 1, NOW - timedelta(days=1)),
        ),
        now=NOW,
    )

    assert result.id == "lower"


def test_skill_tie_uses_question_bank_declaration_order(monkeypatch):
    questions = [_question("first", "first", 1), _question("second", "second", 1)]
    _configure_policy(monkeypatch, questions)

    result = recommend_next_question(mastery_snapshots=(), now=NOW)

    assert result.id == "first"


@pytest.mark.parametrize(
    ("probability", "expected_difficulty"),
    [(0.49, 1), (0.50, 2), (0.80, 3), (1.00, 3)],
)
def test_difficulty_target_boundaries(monkeypatch, probability, expected_difficulty):
    questions = [_question("d1", "skill", 1), _question("d2", "skill", 2), _question("d3", "skill", 3)]
    _configure_policy(monkeypatch, questions)

    result = recommend_next_question(
        mastery_snapshots=(_snapshot("skill", probability, 1, NOW - timedelta(days=8)),),
        now=NOW,
    )

    assert result.difficulty == expected_difficulty


def test_difficulty_uses_nearest_available_question(monkeypatch):
    questions = [_question("d1", "skill", 1), _question("d2", "skill", 2)]
    _configure_policy(monkeypatch, questions)

    result = recommend_next_question(
        mastery_snapshots=(_snapshot("skill", 0.90, 1, NOW - timedelta(days=8)),),
        now=NOW,
    )

    assert result.id == "d2"


def test_equal_distance_prefers_lower_difficulty(monkeypatch):
    questions = [_question("d1", "skill", 1), _question("d3", "skill", 3)]
    _configure_policy(monkeypatch, questions)

    result = recommend_next_question(
        mastery_snapshots=(_snapshot("skill", 0.60, 1, NOW - timedelta(days=4)),),
        now=NOW,
    )

    assert result.id == "d1"


def test_question_tie_uses_question_bank_declaration_order(monkeypatch):
    questions = [_question("first", "skill", 1), _question("second", "skill", 1)]
    _configure_policy(monkeypatch, questions)

    result = recommend_next_question(mastery_snapshots=(), now=NOW)

    assert result.id == "first"


@pytest.mark.parametrize(
    "snapshots",
    [
        (_snapshot("skill", 0.35, 0), _snapshot("skill", 0.35, 0)),
        (_snapshot("unknown", 0.35, 0),),
        (_snapshot("skill alias", 0.35, 0),),
        (_snapshot("skill", -0.01, 0),),
        (_snapshot("skill", 1.01, 0),),
        (_snapshot("skill", True, 0),),
        (_snapshot("skill", 0.35, -1),),
        (_snapshot("skill", 0.35, True),),
        (_snapshot("skill", 0.35, 1.5),),
        (_snapshot("skill", 0.35, 0, "not-a-datetime"),),
    ],
    ids=[
        "duplicate",
        "unknown",
        "alias",
        "probability_below_range",
        "probability_above_range",
        "probability_bool",
        "negative_exposures",
        "exposures_bool",
        "exposures_not_integer",
        "last_seen_not_datetime",
    ],
)
def test_invalid_mastery_snapshots_are_rejected_before_selection(monkeypatch, snapshots):
    questions = [_question("question", "skill", 1), _question("blocked", "blocked", 1)]
    _configure_policy(
        monkeypatch,
        questions,
        {"blocked": ("prerequisite",)},
        {"skill", "blocked", "prerequisite"},
    )

    with pytest.raises(ValueError):
        recommend_next_question(mastery_snapshots=snapshots, now=NOW)


def test_invalid_blocked_skill_snapshot_is_validated_before_selection(monkeypatch):
    questions = [_question("question", "skill", 1), _question("blocked", "blocked", 1)]
    _configure_policy(
        monkeypatch,
        questions,
        {"blocked": ("prerequisite",)},
        {"skill", "blocked", "prerequisite"},
    )

    with pytest.raises(ValueError):
        recommend_next_question(
            mastery_snapshots=(
                _snapshot("skill", 0.35, 0),
                _snapshot("blocked", -0.01, 0),
            ),
            now=NOW,
        )


@pytest.mark.parametrize("invalid_now", ["not-a-datetime", None])
def test_invalid_now_is_rejected(monkeypatch, invalid_now):
    _configure_policy(monkeypatch, [_question("question", "skill", 1)])

    with pytest.raises(ValueError):
        recommend_next_question(mastery_snapshots=(), now=invalid_now)


def test_naive_and_aware_datetimes_cannot_be_mixed(monkeypatch):
    _configure_policy(monkeypatch, [_question("question", "skill", 1)])

    with pytest.raises(ValueError):
        recommend_next_question(
            mastery_snapshots=(
                _snapshot("skill", 0.35, 1, NOW.replace(tzinfo=timezone.utc)),
            ),
            now=NOW,
        )
