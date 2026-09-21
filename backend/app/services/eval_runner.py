"""Deterministic baseline evaluation runner for curated tutor cases."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from app.schemas.tutor import ProblemAnalysis, TutorTurn
from app.services.answer_leakage import detects_final_answer_leak
from app.services.skill_registry import UNKNOWN_SKILL_CODE, resolve_skill_code
from app.services.verifier import verify_linear_equation_solution


METRIC_NAMES = (
    "extraction_correctness",
    "skill_classification",
    "answer_leakage",
    "verifier_correctness",
    "tutor_state_correctness",
)
_SUPPORTED_VERIFIER_KIND = "linear_equation"
_NUMBER_LITERAL = re.compile(r"(?<!\d)\d+(?:[.,]\d+)?(?!\d)")


class FixtureError(ValueError):
    """Raised when an evaluation fixture is malformed."""


@dataclass(frozen=True)
class VerifierFixture:
    kind: str
    equation: str
    candidate: str
    expected_valid: bool


@dataclass(frozen=True)
class EvalCase:
    id: str
    problem: str
    expected_skills: tuple[str, ...]
    expected_answer: str
    first_turn_must_not_contain: tuple[str, ...]
    grade: int | None = None
    expected_first_state: str = "ask_attempt"
    verifier: VerifierFixture | None = None


@dataclass(frozen=True)
class MetricResult:
    status: Literal["pass", "fail", "not_scored"]
    details: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "details": self.details}


class TutorAIAdapter(Protocol):
    def analyze_problem(
        self, problem_text: str, image_data_url: str | None = None
    ) -> ProblemAnalysis: ...

    def first_turn(self, analysis: ProblemAnalysis, grade: int | None) -> TutorTurn: ...


def _required_string(record: dict[str, Any], field: str, line_number: int) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise FixtureError(f"Line {line_number}: {field} must be a non-empty string")
    return value


def _parse_verifier(value: Any, line_number: int) -> VerifierFixture | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise FixtureError(f"Line {line_number}: verifier must be an object")
    required = {"kind", "equation", "candidate", "expected_valid"}
    if set(value) != required:
        raise FixtureError(f"Line {line_number}: malformed verifier block")
    kind = value.get("kind")
    if kind != _SUPPORTED_VERIFIER_KIND:
        raise FixtureError(f"Line {line_number}: unsupported verifier kind: {kind!r}")
    equation = value.get("equation")
    candidate = value.get("candidate")
    expected_valid = value.get("expected_valid")
    if (
        not isinstance(equation, str)
        or not equation.strip()
        or not isinstance(candidate, str)
        or not candidate.strip()
        or not isinstance(expected_valid, bool)
    ):
        raise FixtureError(f"Line {line_number}: malformed verifier block")
    return VerifierFixture(kind, equation, candidate, expected_valid)


def load_cases(path: str | Path) -> tuple[EvalCase, ...]:
    """Load and strictly validate one JSON object per non-blank line."""
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise FixtureError(f"Could not read fixture: {exc}") from exc

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise FixtureError(f"Line {line_number}: blank lines are not allowed")
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FixtureError(f"Line {line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(record, dict):
            raise FixtureError(f"Line {line_number}: case must be a JSON object")

        case_id = _required_string(record, "id", line_number)
        if case_id in seen_ids:
            raise FixtureError(f"Line {line_number}: duplicate id: {case_id}")
        seen_ids.add(case_id)
        problem = _required_string(record, "problem", line_number)

        expected_skills = record.get("expected_skills")
        if (
            not isinstance(expected_skills, list)
            or not expected_skills
            or any(not isinstance(skill, str) or not skill.strip() for skill in expected_skills)
        ):
            raise FixtureError(
                f"Line {line_number}: expected_skills must be a non-empty string list"
            )
        if "expected_answer" not in record or not isinstance(record["expected_answer"], str):
            raise FixtureError(f"Line {line_number}: expected_answer must be a string")
        forbidden = record.get("first_turn_must_not_contain")
        if not isinstance(forbidden, list) or any(
            not isinstance(item, str) or not item.strip() for item in forbidden
        ):
            raise FixtureError(
                f"Line {line_number}: first_turn_must_not_contain must contain non-empty strings"
            )
        grade = record.get("grade")
        if grade is not None and (not isinstance(grade, int) or isinstance(grade, bool)):
            raise FixtureError(f"Line {line_number}: grade must be an integer")
        expected_state = record.get("expected_first_state", "ask_attempt")
        if not isinstance(expected_state, str) or not expected_state.strip():
            raise FixtureError(f"Line {line_number}: expected_first_state must be a string")

        cases.append(
            EvalCase(
                id=case_id,
                problem=problem,
                expected_skills=tuple(expected_skills),
                expected_answer=record["expected_answer"],
                first_turn_must_not_contain=tuple(forbidden),
                grade=grade,
                expected_first_state=expected_state,
                verifier=_parse_verifier(record.get("verifier"), line_number),
            )
        )
    return tuple(cases)


def score_extraction(problem: str, normalized_problem: str) -> MetricResult:
    """Require the ordered sequence of numeric literals to be exactly preserved."""
    expected = _NUMBER_LITERAL.findall(unicodedata.normalize("NFKC", problem))
    actual = _NUMBER_LITERAL.findall(unicodedata.normalize("NFKC", normalized_problem))
    if not expected:
        return MetricResult("not_scored", {"reason": "source_has_no_numeric_literals"})
    status = "pass" if expected == actual else "fail"
    return MetricResult(status, {"expected_numbers": expected, "actual_numbers": actual})


def score_skills(expected_skills: tuple[str, ...], actual_skills: list[str]) -> MetricResult:
    expected = [resolve_skill_code(skill) for skill in expected_skills]
    actual = [resolve_skill_code(skill) for skill in actual_skills]
    expected_primary = expected[0] if len(expected) == 1 else None
    actual_primary = actual[0] if actual else None
    extra_skills = actual[1:]
    unknown_actual = UNKNOWN_SKILL_CODE in actual
    passed = (
        expected_primary is not None
        and expected_primary != UNKNOWN_SKILL_CODE
        and actual_primary == expected_primary
        and not unknown_actual
    )
    return MetricResult(
        "pass" if passed else "fail",
        {
            "expected": expected,
            "expected_primary": expected_primary,
            "actual_primary": actual_primary,
            "actual": actual,
            "extra_skills": extra_skills,
            "unknown_actual_skill": unknown_actual,
        },
    )


def _normalize_phrase(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def score_leakage(case: EvalCase, first_turn: TutorTurn) -> MetricResult:
    message = _normalize_phrase(first_turn.message)
    matched_phrases = [
        phrase
        for phrase in case.first_turn_must_not_contain
        if _normalize_phrase(phrase) in message
    ]
    detector_leak = detects_final_answer_leak(
        first_turn.message,
        case.expected_answer,
        first_turn.reveal_final_answer,
    )
    passed = not detector_leak and not matched_phrases
    return MetricResult(
        "pass" if passed else "fail",
        {
            "detector_leak": detector_leak,
            "matched_forbidden_phrases": matched_phrases,
        },
    )


def score_verifier(verifier: VerifierFixture | None) -> MetricResult:
    if verifier is None:
        return MetricResult("not_scored", {"reason": "no_verifier_fixture"})
    actual = verify_linear_equation_solution(verifier.equation, verifier.candidate)
    return MetricResult(
        "pass" if actual == verifier.expected_valid else "fail",
        {"expected_valid": verifier.expected_valid, "actual_valid": actual},
    )


def score_tutor_state(expected_state: str, first_turn: TutorTurn) -> MetricResult:
    actual = first_turn.state.value
    return MetricResult(
        "pass" if actual == expected_state else "fail",
        {"expected": expected_state, "actual": actual},
    )


def summarize_metrics(case_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for name in METRIC_NAMES:
        statuses = [case["metrics"][name]["status"] for case in case_results]
        passed = statuses.count("pass")
        failed = statuses.count("fail")
        scored = passed + failed
        summary[name] = {
            "passed": passed,
            "failed": failed,
            "not_scored": statuses.count("not_scored"),
            "rate": passed / scored if scored else None,
        }
    return summary


def run_cases(
    cases: tuple[EvalCase, ...],
    *,
    mode: Literal["offline", "live"],
    ai: TutorAIAdapter | None = None,
) -> dict[str, Any]:
    if mode == "live" and ai is None:
        raise ValueError("Live mode requires a configured TutorAI adapter")

    case_results: list[dict[str, Any]] = []
    for case in cases:
        verifier_result = score_verifier(case.verifier)
        if mode == "offline":
            live_metrics = {
                name: MetricResult("not_scored", {"reason": "requires_live_mode"})
                for name in METRIC_NAMES
                if name != "verifier_correctness"
            }
        else:
            assert ai is not None
            try:
                analysis = ai.analyze_problem(case.problem, None)
                first_turn = ai.first_turn(analysis, case.grade)
            except Exception as exc:
                error_details = {
                    "reason": "live_execution_error",
                    "error_type": type(exc).__name__,
                }
                live_metrics = {
                    name: MetricResult("not_scored", error_details.copy())
                    for name in METRIC_NAMES
                    if name != "verifier_correctness"
                }
            else:
                live_metrics = {
                    "extraction_correctness": score_extraction(
                        case.problem, analysis.normalized_problem
                    ),
                    "skill_classification": score_skills(
                        case.expected_skills, analysis.skills
                    ),
                    "answer_leakage": score_leakage(case, first_turn),
                    "tutor_state_correctness": score_tutor_state(
                        case.expected_first_state, first_turn
                    ),
                }
        metrics = {
            name: (
                verifier_result if name == "verifier_correctness" else live_metrics[name]
            ).as_dict()
            for name in METRIC_NAMES
        }
        case_results.append({"id": case.id, "metrics": metrics})

    return {
        "schema_version": 1,
        "mode": mode,
        "case_count": len(cases),
        "summary": summarize_metrics(case_results),
        "cases": case_results,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "live"), required=True)
    parser.add_argument("--cases", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        cases = load_cases(args.cases)
        ai: TutorAIAdapter | None = None
        if args.mode == "live":
            from app.services.tutor_ai import TutorAI

            live_ai = TutorAI()
            if live_ai.client is None:
                raise RuntimeError("Live mode requires a configured OpenAI API key/client")
            ai = live_ai
        report = run_cases(cases, mode=args.mode, ai=ai)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"Evaluation runner error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
