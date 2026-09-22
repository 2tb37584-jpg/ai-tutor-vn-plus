from collections import Counter, defaultdict
from pathlib import Path

from app.services.eval_runner import load_cases, run_cases


BENCHMARK_PATH = Path(__file__).resolve().parent / "data" / "verifier_supported_domain.jsonl"
SUPPORTED_FAMILIES = {
    "linear_equation",
    "expression_equivalence",
    "numeric",
}


def test_supported_domain_verifier_benchmark() -> None:
    cases = load_cases(BENCHMARK_PATH)

    assert len(cases) == 60
    assert len({case.id for case in cases}) == 60
    assert all(case.verifier is not None for case in cases)

    fixtures = [case.verifier for case in cases if case.verifier is not None]
    families = Counter(fixture.family for fixture in fixtures)
    statuses = Counter(fixture.expected_status for fixture in fixtures)
    assert families == {family: 20 for family in SUPPORTED_FAMILIES}
    assert statuses == {"correct": 30, "incorrect": 30}
    assert all(fixture.expected_status not in {"unsupported", "indeterminate"} for fixture in fixtures)
    for family in SUPPORTED_FAMILIES:
        family_statuses = Counter(
            fixture.expected_status for fixture in fixtures if fixture.family == family
        )
        assert family_statuses == {"correct": 10, "incorrect": 10}

    report = run_cases(cases, mode="offline")
    metrics = {
        case["id"]: case["metrics"]["verifier_correctness"]
        for case in report["cases"]
    }
    scored = [metric for metric in metrics.values() if metric["status"] != "not_scored"]
    passed = sum(metric["status"] == "pass" for metric in scored)
    failed_ids = [case_id for case_id, metric in metrics.items() if metric["status"] == "fail"]
    per_family_results: dict[str, list[bool]] = defaultdict(list)
    for case in cases:
        assert case.verifier is not None
        per_family_results[case.verifier.family].append(
            metrics[case.id]["status"] == "pass"
        )
    per_family_rates = {
        family: sum(results) / len(results)
        for family, results in per_family_results.items()
    }
    rate = passed / len(scored)

    print(
        "VERIFIER_BENCHMARK "
        f"total={len(cases)} passed={passed} failed={len(failed_ids)} rate={rate:.4f} "
        f"linear_equation={per_family_rates['linear_equation']:.4f} "
        f"expression_equivalence={per_family_rates['expression_equivalence']:.4f} "
        f"numeric={per_family_rates['numeric']:.4f}"
    )
    if failed_ids:
        print(f"VERIFIER_BENCHMARK_FAILURES ids={','.join(failed_ids)}")

    assert len(scored) == 60
    assert rate >= 0.98
