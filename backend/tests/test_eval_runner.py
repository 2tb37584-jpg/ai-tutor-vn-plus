import json

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


def test_skill_classification_canonicalizes_and_rejects_unknown():
    expected = ("algebra.linear_equation",)
    assert score_skills(expected, ["linear equation"]).status == "pass"
    assert score_skills(expected, ["algebra.factorization"]).status == "fail"
    result = score_skills(expected, ["invented.skill"])
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
