import json
import os
from collections import Counter
from pathlib import Path

import pytest

from app.schemas.tutor import ProblemAnalysis, TutorState, TutorTurn
from app.services.eval_runner import (
    METRIC_NAMES,
    EvalCase,
    FixtureError,
    VerifierFixture,
    load_cases,
    run_cases,
    score_extraction,
    score_leakage,
    score_skills,
    score_tutor_state,
    summarize_metrics,
)


REQUIRED_CANONICAL_SKILLS = {
    "arithmetic.signed_number_operations",
    "algebra.expression.distributive_property",
    "algebra.expression.combine_like_terms",
    "algebra.expression.simplify",
    "algebra.equation.equivalent_transform",
    "algebra.linear_equation",
    "algebra.identity.basic",
    "algebra.factorization",
    "algebra.rational_expression.domain",
    "algebra.rational_expression.simplify",
}
CANONICAL_CASES_ENV = "AI_TUTOR_CANONICAL_EVAL_CASES"
M09_07_CANONICAL_IDS = {
    "g8-signed-numbers-negative-division-chain-001",
    "g8-signed-numbers-subtract-product-001",
    "g8-signed-numbers-negative-product-subtract-001",
    "g8-distributive-two-groups-001",
    "g8-distributive-negated-group-plus-001",
    "g8-combine-like-terms-leading-negative-one-001",
    "g8-combine-like-terms-constant-cancel-001",
    "g8-combine-like-terms-reordered-001",
    "g8-expression-simplify-negated-group-001",
    "g8-expression-simplify-nested-bracket-001",
    "g8-equivalent-transform-divide-parenthesized-side-001",
    "g8-equivalent-transform-subtract-variable-both-sides-001",
    "g8-identity-scaled-sum-square-002",
    "g8-identity-recognize-perfect-square-sum-001",
    "g8-identity-recognize-difference-squares-001",
    "g8-factor-common-factor-difference-squares-001",
    "g8-factor-leading-coefficient-negative-middle-001",
    "g8-rational-domain-factorable-quadratic-001",
    "g8-rational-domain-zero-factor-001",
    "g8-rational-simplify-partial-cancellation-001",
}
EXPECTED_CANONICAL_IDS = {
    "g8-linear-001",
    "g8-factor-001",
    "g8-rational-domain-001",
    "g8-linear-leakage-guard-001",
    "g8-linear-negative-leakage-001",
    "g8-linear-fraction-leakage-001",
    "g8-distributive-leakage-001",
    "g8-factor-sign-leakage-001",
    "g8-rational-domain-notation-leakage-001",
    "g8-signed-numbers-001",
    "g8-combine-like-terms-001",
    "g8-expression-simplify-001",
    "g8-equivalent-transform-001",
    "g8-identity-square-sum-001",
    "g8-rational-simplify-001",
    "g8-distributive-sign-001",
    "g8-combine-like-terms-sign-001",
    "g8-expression-simplify-002",
    "g8-identity-difference-squares-001",
    "g8-linear-verifier-negative-001",
    "g8-signed-numbers-mixed-001",
    "g8-signed-numbers-product-001",
    "g8-signed-numbers-division-001",
    "g8-distributive-coefficient-001",
    "g8-distributive-negative-002",
    "g8-combine-like-terms-002",
    "g8-combine-like-terms-negative-001",
    "g8-expression-simplify-003",
    "g8-expression-simplify-negative-001",
    "g8-equivalent-transform-add-001",
    "g8-equivalent-transform-divide-001",
    "g8-equivalent-transform-subtract-001",
    "g8-identity-square-difference-001",
    "g8-identity-scaled-square-001",
    "g8-factor-trinomial-002",
    "g8-factor-difference-squares-001",
    "g8-rational-domain-positive-001",
    "g8-rational-domain-linear-denominator-001",
    "g8-rational-simplify-difference-squares-001",
    "g8-rational-simplify-factor-001",
    "g8-signed-numbers-subtract-negative-001",
    "g8-signed-numbers-order-operations-001",
    "g8-distributive-leading-subtraction-001",
    "g8-distributive-fraction-001",
    "g8-combine-like-terms-implicit-one-001",
    "g8-combine-like-terms-constants-001",
    "g8-expression-simplify-leading-minus-001",
    "g8-expression-simplify-cancel-variable-001",
    "g8-equivalent-transform-negative-divide-001",
    "g8-equivalent-transform-multiply-001",
    "g8-linear-parentheses-verifier-001",
    "g8-identity-scaled-difference-square-001",
    "g8-identity-scaled-difference-squares-001",
    "g8-factor-common-factor-001",
    "g8-factor-perfect-square-001",
    "g8-rational-domain-scaled-linear-001",
    "g8-rational-domain-two-exclusions-001",
    "g8-rational-simplify-common-factor-001",
    "g8-rational-simplify-difference-squares-denominator-plus-001",
    "g8-rational-simplify-trinomial-001",
    "g8-signed-numbers-nested-sign-001",
    "g8-distributive-double-parentheses-001",
    "g8-distributive-negative-fraction-001",
    "g8-combine-like-terms-zero-coefficient-001",
    "g8-expression-simplify-nested-sign-001",
    "g8-expression-simplify-fraction-coefficient-001",
    "g8-equivalent-transform-add-variable-001",
    "g8-equivalent-transform-clear-denominator-001",
    "g8-linear-both-sides-verifier-001",
    "g8-linear-fraction-solution-verifier-001",
    "g8-linear-zero-solution-verifier-001",
    "g8-linear-verifier-negative-fraction-001",
    "g8-identity-middle-term-sign-001",
    "g8-factor-negative-common-factor-001",
    "g8-factor-leading-coefficient-trinomial-001",
    "g8-rational-domain-quadratic-denominator-001",
    "g8-rational-domain-repeated-factor-001",
    "g8-rational-simplify-negative-factor-001",
    "g8-rational-simplify-repeated-factor-001",
    "g8-rational-simplify-coefficient-factor-001",
} | M09_07_CANONICAL_IDS
EXPECTED_CANONICAL_SKILL_COUNTS = {
    "arithmetic.signed_number_operations": 10,
    "algebra.expression.distributive_property": 10,
    "algebra.expression.combine_like_terms": 10,
    "algebra.expression.simplify": 10,
    "algebra.equation.equivalent_transform": 10,
    "algebra.linear_equation": 10,
    "algebra.identity.basic": 10,
    "algebra.factorization": 10,
    "algebra.rational_expression.domain": 10,
    "algebra.rational_expression.simplify": 10,
}


def _canonical_cases_path() -> Path:
    configured = os.getenv(CANONICAL_CASES_ENV)
    if configured:
        return Path(configured)

    repository_path = Path(__file__).resolve().parents[2] / "evals" / "cases.jsonl"
    if repository_path.exists():
        return repository_path

    pytest.skip("canonical eval corpus is not mounted in this test environment")


def _record(**updates):
    record = {
        "id": "case-1",
        "problem": "2x + 3 = 11",
        "expected_skills": ["algebra.linear_equation"],
        "expected_answer": "4",
        "first_turn_must_not_contain": ["x = 4"],
        "grade": 8,
        "expected_first_state": "ask_attempt",
    }
    record.update(updates)
    return record


def _write_cases(tmp_path, *records):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
        encoding="utf-8",
    )
    return path


def _case(**updates):
    values = {
        "id": "case-1",
        "problem": "2x + 3 = 11",
        "expected_skills": ("algebra.linear_equation",),
        "expected_answer": "4",
        "first_turn_must_not_contain": ("x = 4",),
        "grade": 8,
        "expected_first_state": "ask_attempt",
    }
    values.update(updates)
    return EvalCase(**values)


class FakeAI:
    def __init__(self, *, normalized_problem="2x + 3 = 11", skills=None, state=TutorState.ASK_ATTEMPT):
        self.normalized_problem = normalized_problem
        self.skills = skills or ["algebra.linear_equation"]
        self.state = state
        self.calls = []

    def analyze_problem(self, problem_text, image_data_url=None):
        self.calls.append(("analyze", problem_text, image_data_url))
        return ProblemAnalysis(
            normalized_problem=self.normalized_problem,
            skills=self.skills,
            expected_answer="internal",
        )

    def first_turn(self, analysis, grade):
        self.calls.append(("first_turn", analysis, grade))
        return TutorTurn(message="Em hãy thử bước đầu tiên.", state=self.state)


def test_valid_jsonl_loads(tmp_path):
    cases = load_cases(_write_cases(tmp_path, _record()))
    assert cases[0].id == "case-1"
    assert cases[0].grade == 8
    assert cases[0].expected_first_state == "ask_attempt"


def test_canonical_corpus_has_required_count_and_skill_coverage():
    cases = load_cases(_canonical_cases_path())

    assert len(cases) == 100
    assert {case.id for case in cases} == EXPECTED_CANONICAL_IDS
    assert all(case.grade == 8 for case in cases)
    assert all(case.expected_first_state == "ask_attempt" for case in cases)

    represented_skills = {
        skill
        for case in cases
        for skill in case.expected_skills
    }
    assert represented_skills == REQUIRED_CANONICAL_SKILLS
    assert "general.problem_solving" not in represented_skills
    assert Counter(
        skill for case in cases for skill in case.expected_skills
    ) == EXPECTED_CANONICAL_SKILL_COUNTS

    negative_verifier_case = next(
        case for case in cases if case.id == "g8-linear-verifier-negative-001"
    )
    assert negative_verifier_case.verifier is not None
    assert negative_verifier_case.verifier.kind == "linear_equation"
    assert negative_verifier_case.verifier.expected_valid is False

    positive_verifier_case = next(
        case for case in cases if case.id == "g8-linear-parentheses-verifier-001"
    )
    assert positive_verifier_case.verifier is not None
    assert positive_verifier_case.verifier.kind == "linear_equation"
    assert positive_verifier_case.verifier.expected_valid is True

    verifier_fixtures = [case.verifier for case in cases if case.verifier is not None]
    assert len(verifier_fixtures) == 8
    assert {verifier.kind for verifier in verifier_fixtures} == {"linear_equation"}
    assert Counter(
        verifier.expected_valid for verifier in verifier_fixtures
    ) == {True: 6, False: 2}

    expected_verifier_validity = {
        "g8-linear-verifier-negative-fraction-001": False,
        "g8-linear-both-sides-verifier-001": True,
        "g8-linear-fraction-solution-verifier-001": True,
        "g8-linear-zero-solution-verifier-001": True,
    }
    for case_id, expected_valid in expected_verifier_validity.items():
        verifier_case = next(case for case in cases if case.id == case_id)
        assert verifier_case.verifier is not None
        assert verifier_case.verifier.kind == "linear_equation"
        assert verifier_case.verifier.expected_valid is expected_valid

    m09_07_cases = [case for case in cases if case.id in M09_07_CANONICAL_IDS]
    assert len(m09_07_cases) == 20
    assert all(case.verifier is None for case in m09_07_cases)


def test_invalid_json_fails(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(FixtureError, match="invalid JSON"):
        load_cases(path)


def test_duplicate_id_fails(tmp_path):
    with pytest.raises(FixtureError, match="duplicate id"):
        load_cases(_write_cases(tmp_path, _record(), _record()))


@pytest.mark.parametrize(
    "updates, message",
    [
        ({"id": ""}, "id"),
        ({"problem": " "}, "problem"),
        ({"expected_skills": []}, "expected_skills"),
        ({"expected_answer": None}, "expected_answer"),
        ({"first_turn_must_not_contain": "x=4"}, "first_turn_must_not_contain"),
    ],
)
def test_missing_or_invalid_required_field_fails(tmp_path, updates, message):
    with pytest.raises(FixtureError, match=message):
        load_cases(_write_cases(tmp_path, _record(**updates)))


@pytest.mark.parametrize("phrase", ["", "   "])
def test_blank_forbidden_phrase_fails(tmp_path, phrase):
    with pytest.raises(FixtureError, match="non-empty strings"):
        load_cases(
            _write_cases(
                tmp_path,
                _record(first_turn_must_not_contain=[phrase]),
            )
        )


def test_non_object_and_blank_lines_fail(tmp_path):
    with pytest.raises(FixtureError, match="JSON object"):
        load_cases(_write_cases(tmp_path, [1, 2]))
    path = tmp_path / "blank.jsonl"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(FixtureError, match="blank lines"):
        load_cases(path)


@pytest.mark.parametrize(
    "verifier, message",
    [
        ({"kind": "linear_equation"}, "malformed verifier"),
        ({"kind": "factorization", "equation": "x=1", "candidate": "1", "expected_valid": True}, "unsupported verifier kind"),
    ],
)
def test_invalid_verifier_block_fails(tmp_path, verifier, message):
    with pytest.raises(FixtureError, match=message):
        load_cases(_write_cases(tmp_path, _record(verifier=verifier)))


def test_offline_never_invokes_ai_and_scores_verifier():
    verifier = VerifierFixture("linear_equation", "2*x+3=11", "4", True)
    ai = FakeAI()
    report = run_cases((_case(verifier=verifier),), mode="offline", ai=ai)
    assert ai.calls == []
    metrics = report["cases"][0]["metrics"]
    assert metrics["verifier_correctness"]["status"] == "pass"
    assert all(
        metrics[name]["status"] == "not_scored"
        for name in METRIC_NAMES
        if name != "verifier_correctness"
    )


def test_verifier_mismatch_fails_without_crashing():
    verifier = VerifierFixture("linear_equation", "2*x+3=11", "5", True)
    report = run_cases((_case(verifier=verifier),), mode="offline")
    assert report["cases"][0]["metrics"]["verifier_correctness"]["status"] == "fail"


def test_no_verifier_is_not_scored():
    report = run_cases((_case(),), mode="offline")
    assert report["cases"][0]["metrics"]["verifier_correctness"]["status"] == "not_scored"


def test_not_scored_is_excluded_from_rate():
    case_results = [
        {"metrics": {name: {"status": "not_scored"} for name in METRIC_NAMES}},
        {"metrics": {name: {"status": "pass"} for name in METRIC_NAMES}},
    ]
    summary = summarize_metrics(case_results)
    assert summary["extraction_correctness"] == {
        "passed": 1,
        "failed": 0,
        "not_scored": 1,
        "rate": 1.0,
    }


def test_extraction_uses_ordered_numeric_literal_preservation():
    assert score_extraction("2x + 3 = 11", "Giải 2x + 3 = 11").status == "pass"
    assert score_extraction("2x + 3 = 11", "2x + 4 = 11").status == "fail"
    assert score_extraction("2x + 3 = 11", "2x + 3").status == "fail"
    assert score_extraction("Tìm x", "Tìm biến x").status == "not_scored"


def test_skill_classification_canonicalizes_primary_skill_aliases():
    result = score_skills(("algebra.linear_equation",), ["linear equation"])

    assert result.status == "pass"
    assert result.details["expected_primary"] == "algebra.linear_equation"
    assert result.details["actual_primary"] == "algebra.linear_equation"


def test_skill_classification_passes_exact_primary_match():
    result = score_skills(("algebra.identity.basic",), ["algebra.identity.basic"])

    assert result.status == "pass"
    assert result.details["extra_skills"] == []


def test_skill_classification_allows_controlled_secondary_skills():
    result = score_skills(
        ("algebra.identity.basic",),
        ["algebra.identity.basic", "algebra.expression.distributive_property"],
    )

    assert result.status == "pass"
    assert result.details == {
        "expected": ["algebra.identity.basic"],
        "expected_primary": "algebra.identity.basic",
        "actual_primary": "algebra.identity.basic",
        "actual": [
            "algebra.identity.basic",
            "algebra.expression.distributive_property",
        ],
        "extra_skills": ["algebra.expression.distributive_property"],
        "unknown_actual_skill": False,
    }


def test_skill_classification_rejects_correct_skill_after_wrong_primary():
    result = score_skills(
        ("algebra.identity.basic",),
        ["algebra.expression.distributive_property", "algebra.identity.basic"],
    )

    assert result.status == "fail"
    assert result.details["actual_primary"] == "algebra.expression.distributive_property"
    assert result.details["extra_skills"] == ["algebra.identity.basic"]


def test_skill_classification_rejects_unknown_secondary_skill():
    result = score_skills(
        ("algebra.identity.basic",),
        ["algebra.identity.basic", "invented.skill"],
    )

    assert result.status == "fail"
    assert result.details["unknown_actual_skill"] is True
    assert result.details["actual"] == ["algebra.identity.basic", "unknown"]


@pytest.mark.parametrize(
    "actual_skills",
    [
        ["invented.skill", "algebra.identity.basic"],
        [],
    ],
)
def test_skill_classification_rejects_unknown_or_missing_primary(actual_skills):
    result = score_skills(("algebra.identity.basic",), actual_skills)

    assert result.status == "fail"
    if not actual_skills:
        assert result.details["actual_primary"] is None


def test_skill_classification_rejects_different_controlled_primary():
    result = score_skills(
        ("algebra.linear_equation",),
        ["algebra.factorization"],
    )

    assert result.status == "fail"
    assert result.details["actual_primary"] == "algebra.factorization"


def test_skill_classification_preserves_multiple_controlled_extras():
    result = score_skills(
        ("algebra.identity.basic",),
        [
            "algebra.identity.basic",
            "algebra.expression.distributive_property",
            "algebra.expression.simplify",
        ],
    )

    assert result.status == "pass"
    assert result.details["extra_skills"] == [
        "algebra.expression.distributive_property",
        "algebra.expression.simplify",
    ]


def test_skill_classification_rejects_multi_skill_expectations():
    result = score_skills(
        (
            "algebra.identity.basic",
            "algebra.expression.distributive_property",
        ),
        ["algebra.identity.basic"],
    )

    assert result.status == "fail"
    assert result.details["expected"] == [
        "algebra.identity.basic",
        "algebra.expression.distributive_property",
    ]
    assert result.details["expected_primary"] is None


def test_skill_classification_rejects_unknown_actual_skill():
    result = score_skills(("algebra.linear_equation",), ["invented.skill"])
    assert result.status == "fail"
    assert result.details["unknown_actual_skill"] is True


def test_leakage_checks_forbidden_phrases_and_existing_detector():
    case = _case(first_turn_must_not_contain=("ĐÁP ÁN   LÀ 4",))
    phrase_leak = TutorTurn(message="đáp án là 4")
    detector_leak = TutorTurn(message="Ta có x = 4")
    safe = TutorTurn(message="Em sẽ làm phép tính nào trước?")
    assert score_leakage(case, phrase_leak).status == "fail"
    assert score_leakage(_case(first_turn_must_not_contain=()), detector_leak).status == "fail"
    assert score_leakage(case, safe).status == "pass"


@pytest.mark.parametrize(
    ("expected_answer", "message"),
    [
        ("4", "Đáp án là 4"),
        ("4", "Ta có x = 4"),
        ("(x-2)(x-3)", "Ta được (x-2)(x-3)"),
    ],
)
def test_composite_leakage_detector_hits(expected_answer, message):
    result = score_leakage(
        _case(expected_answer=expected_answer, first_turn_must_not_contain=()),
        TutorTurn(message=message),
    )
    assert result.status == "fail"
    assert result.details == {
        "detector_leak": True,
        "matched_forbidden_phrases": [],
    }


def test_composite_forbidden_phrase_alone_is_normalized_and_sufficient():
    result = score_leakage(
        _case(
            expected_answer="different answer",
            first_turn_must_not_contain=("ĐÁP ÁN   PHỤ LÀ ４", "unused phrase"),
        ),
        TutorTurn(message="đáp án phụ là 4"),
    )
    assert result.status == "fail"
    assert result.details["detector_leak"] is False
    assert result.details["matched_forbidden_phrases"] == ["ĐÁP ÁN   PHỤ LÀ ４"]


def test_composite_notation_variant_is_caught_by_fixture_phrase():
    result = score_leakage(
        _case(
            expected_answer="x != 2",
            first_turn_must_not_contain=("x ≠ 2",),
        ),
        TutorTurn(message="Điều kiện là x ≠ 2"),
    )
    assert result.status == "fail"
    assert result.details == {
        "detector_leak": False,
        "matched_forbidden_phrases": ["x ≠ 2"],
    }


def test_composite_safe_turn_passes_with_empty_mechanism_details():
    result = score_leakage(
        _case(),
        TutorTurn(message="Em hãy thử xác định phép tính đầu tiên."),
    )
    assert result.status == "pass"
    assert result.details == {
        "detector_leak": False,
        "matched_forbidden_phrases": [],
    }


def test_composite_model_self_report_causes_failure():
    result = score_leakage(
        _case(first_turn_must_not_contain=()),
        TutorTurn(message="Em hãy thử bước đầu tiên.", reveal_final_answer=True),
    )
    assert result.status == "fail"
    assert result.details["detector_leak"] is True
    assert result.details["matched_forbidden_phrases"] == []


def test_tutor_state_scoring():
    assert score_tutor_state("ask_attempt", TutorTurn(message="Q", state=TutorState.ASK_ATTEMPT)).status == "pass"
    assert score_tutor_state("ask_attempt", TutorTurn(message="Q", state=TutorState.HINT_1)).status == "fail"


def test_fake_live_run_has_all_metrics_correct_calls_and_summary():
    ai = FakeAI()
    report = run_cases((_case(),), mode="live", ai=ai)
    assert [call[0] for call in ai.calls] == ["analyze", "first_turn"]
    assert ai.calls[0][2] is None
    assert ai.calls[1][2] == 8
    assert set(report["cases"][0]["metrics"]) == set(METRIC_NAMES)
    assert report["summary"]["extraction_correctness"]["rate"] == 1.0
    assert report["summary"]["verifier_correctness"]["rate"] is None
    assert json.loads(json.dumps(report, ensure_ascii=False))["schema_version"] == 1


def test_live_metric_failures_remain_in_report():
    ai = FakeAI(
        normalized_problem="2x + 4 = 11",
        skills=["invented.skill"],
        state=TutorState.HINT_1,
    )
    report = run_cases((_case(),), mode="live", ai=ai)
    assert report["summary"]["extraction_correctness"]["failed"] == 1
    assert report["summary"]["skill_classification"]["failed"] == 1
    assert report["summary"]["tutor_state_correctness"]["failed"] == 1


def test_live_execution_error_is_isolated_and_later_case_still_runs():
    verifier = VerifierFixture("linear_equation", "2*x+3=11", "4", True)

    class SelectivelyFailingAI(FakeAI):
        def analyze_problem(self, problem_text, image_data_url=None):
            self.calls.append(("analyze", problem_text, image_data_url))
            if problem_text == "failing problem":
                raise RuntimeError("sensitive exception payload must not be reported")
            return ProblemAnalysis(
                normalized_problem=problem_text,
                skills=self.skills,
                expected_answer="internal",
            )

    ai = SelectivelyFailingAI()
    cases = (
        _case(id="failing", problem="failing problem", verifier=verifier),
        _case(id="passing", problem="2x + 3 = 11"),
    )

    report = run_cases(cases, mode="live", ai=ai)

    assert [result["id"] for result in report["cases"]] == ["failing", "passing"]
    failed_metrics = report["cases"][0]["metrics"]
    assert failed_metrics["verifier_correctness"]["status"] == "pass"
    for name in METRIC_NAMES:
        if name == "verifier_correctness":
            continue
        assert failed_metrics[name] == {
            "status": "not_scored",
            "details": {
                "reason": "live_execution_error",
                "error_type": "RuntimeError",
            },
        }
    assert "sensitive exception payload" not in json.dumps(report)

    passing_metrics = report["cases"][1]["metrics"]
    assert passing_metrics["extraction_correctness"]["status"] == "pass"
    assert passing_metrics["skill_classification"]["status"] == "pass"
    assert passing_metrics["answer_leakage"]["status"] == "pass"
    assert passing_metrics["tutor_state_correctness"]["status"] == "pass"
    assert [call[0] for call in ai.calls] == ["analyze", "analyze", "first_turn"]
