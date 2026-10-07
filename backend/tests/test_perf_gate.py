"""Performance gates (tracker TEST-041): a benchmark run held against a baseline from the same
machine -- slower or heavier than the tolerance and the floor allow fails, noise doesn't, and a
baseline from another machine is refused."""

import json

import pytest

from scripts import perf_gate
from scripts.perf_gate import OtherMachineError, compare

MACHINE = {"cpu": "Test CPU @ 3.00GHz", "cores": 8, "os": "Windows-10", "git_commit": "abc1234"}
GATES = {"default": {"time_tolerance": 0.5, "time_floor_s": 0.05, "memory_tolerance": 0.5, "memory_floor_kib": 1024}}


def _run(*cases: dict, machine: dict = MACHINE) -> dict:
    return {"machine": machine, "options": "--quick", "results": list(cases)}


def _case(case_id: str, best: float, peak: int | None = None, status: str = "ok", group: str = "save") -> dict:
    case = {"id": case_id, "group": group, "status": status, "best_s": best}
    if peak is not None:
        case["peak_kib"] = peak
    return case


def _verdicts(result) -> dict:
    return {(finding.id, finding.metric): finding.verdict for finding in result.findings}


def test_slower_beyond_the_tolerance_and_the_floor_fails_noise_does_not():
    baseline = _run(_case("save/a", 1.0), _case("save/b", 0.02), _case("save/c", 1.0))
    current = _run(_case("save/a", 1.6), _case("save/b", 0.06), _case("save/c", 1.4))
    result = compare(baseline, current, GATES)
    # a: +60% and +0.6 s: slower. b: three times as slow, but 40 ms: noise. c: +40%: within.
    assert _verdicts(result) == {("save/a", "time"): "slower", ("save/b", "time"): "ok", ("save/c", "time"): "ok"}
    assert not result.passed and [finding.id for finding in result.failures] == ["save/a"]


def test_memory_is_held_the_same_way():
    baseline = _run(_case("load/a", 0.1, peak=10_000), _case("load/b", 0.1, peak=500))
    current = _run(_case("load/a", 0.1, peak=20_000), _case("load/b", 0.1, peak=1_400))
    assert _verdicts(compare(baseline, current, GATES))[("load/a", "memory")] == "more-memory"
    assert _verdicts(compare(baseline, current, GATES))[("load/b", "memory")] == "ok"  # under the 1024 KiB floor


def test_a_case_that_no_longer_finishes_or_is_gone_fails_and_a_new_one_is_listed():
    baseline = _run(_case("export/pdf/a", 1.0), _case("export/docx/a", 1.0), _case("export/pdf/old", 9.0, status="timeout"))
    current = _run(_case("export/pdf/a", 1.0, status="timeout"), _case("export/pdf/new", 1.0))
    verdicts = _verdicts(compare(baseline, current, GATES))
    assert verdicts == {
        ("export/pdf/a", "status"): "failed",
        ("export/docx/a", "status"): "missing",
        ("export/pdf/new", "status"): "new",
    }  # a case that timed out in the baseline holds nothing


def test_group_tolerances_override_the_default():
    gates = {**GATES, "groups": {"export": {"time_tolerance": 2.0}}}
    baseline = _run(_case("export/pdf/a", 1.0, group="export"))
    current = _run(_case("export/pdf/a", 2.5, group="export"))
    assert compare(baseline, current, gates).passed
    assert not compare(baseline, current, GATES).passed


def test_a_baseline_from_another_machine_is_refused():
    other = {**MACHINE, "cpu": "Another CPU @ 2.10GHz"}
    with pytest.raises(OtherMachineError):
        compare(_run(_case("save/a", 1.0)), _run(_case("save/a", 1.0), machine=other), GATES)
    assert compare(_run(_case("save/a", 1.0)), _run(_case("save/a", 1.0), machine=other), GATES, allow_other_machine=True).passed


def test_the_command_exits_by_the_verdict_and_writes_the_report(tmp_path):
    base, head, report = tmp_path / "base.json", tmp_path / "head.json", tmp_path / "gate.md"
    base.write_text(json.dumps(_run(_case("save/a", 1.0))), encoding="utf-8")
    head.write_text(json.dumps(_run(_case("save/a", 3.0))), encoding="utf-8")
    assert perf_gate.main(["--baseline", str(base), "--current", str(head), "--report", str(report)]) == 1
    assert "FAILED" in report.read_text(encoding="utf-8") and "| save/a | time | 1.000 s | 3.000 s | +200% | slower |" in report.read_text(encoding="utf-8")
    head.write_text(json.dumps(_run(_case("save/a", 1.01))), encoding="utf-8")
    assert perf_gate.main(["--baseline", str(base), "--current", str(head)]) == 0
    head.write_text(json.dumps(_run(_case("save/a", 1.0), machine={**MACHINE, "cores": 2})), encoding="utf-8")
    assert perf_gate.main(["--baseline", str(base), "--current", str(head)]) == 2


def test_the_committed_gates_file_is_valid():
    gates = json.loads(perf_gate.DEFAULT_GATES.read_text(encoding="utf-8"))
    for limits in [gates["default"], *gates["groups"].values()]:
        assert set(limits) <= set(perf_gate.FALLBACK) and all(value > 0 for value in limits.values())
