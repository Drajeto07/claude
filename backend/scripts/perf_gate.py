"""Performance gates (tracker TEST-041): a benchmark run (scripts/benchmark.py, PERF-002) held
against a baseline run of the same benchmark on the same machine -- the commit a change starts
from, measured right before it. Numbers from another machine say nothing about a change, so a
baseline from one is refused (--allow-other-machine overrides, for a look, not a verdict).

    python -m scripts.perf_gate --baseline base/benchmarks.json --current head/benchmarks.json
    python -m scripts.perf_gate ... --report gate.md     # the table as Markdown too

A case fails when it got slower than its tolerance allows AND by more than the floor: the best of
the repeats is compared (the least disturbed by other work on the machine), a quarter or half
again is the usual tolerance (docs/performance/gates.json), and a few tens of milliseconds never
count -- below that, timing is noise. Python memory (tracemalloc's peak) is held the same way.
A case that finished in the baseline but times out, fails or is missing now fails too. A case
only the current run has is listed, not judged. Exit code 1 when any case fails."""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_GATES = Path(__file__).resolve().parent.parent.parent / "docs" / "performance" / "gates.json"
FALLBACK = {"time_tolerance": 0.5, "time_floor_s": 0.05, "memory_tolerance": 0.5, "memory_floor_kib": 1024}


class OtherMachineError(Exception):
    """The two runs weren't measured on the same machine."""


@dataclass
class Finding:
    id: str
    metric: str  # time | memory | status
    baseline: float | str | None
    current: float | str | None
    verdict: str  # ok | slower | more-memory | failed | missing | new

    @property
    def failed(self) -> bool:
        return self.verdict in ("slower", "more-memory", "failed", "missing")


@dataclass
class GateResult:
    findings: list[Finding] = field(default_factory=list)

    @property
    def failures(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.failed]

    @property
    def passed(self) -> bool:
        return not self.failures


def _limits(gates: dict, group: str) -> dict:
    return {**FALLBACK, **gates.get("default", {}), **gates.get("groups", {}).get(group, {})}


def _same_machine(baseline: dict, current: dict) -> bool:
    keys = ("cpu", "cores", "os")
    return all(baseline.get("machine", {}).get(key) == current.get("machine", {}).get(key) for key in keys)


def compare(baseline: dict, current: dict, gates: dict | None = None, *, allow_other_machine: bool = False) -> GateResult:
    """Every case of the baseline held against the current run (see the module's docstring)."""
    if not allow_other_machine and not _same_machine(baseline, current):
        raise OtherMachineError(
            f"the baseline was measured on {baseline.get('machine', {}).get('cpu')!r}, this run on "
            f"{current.get('machine', {}).get('cpu')!r}: run both on one machine"
        )
    gates = gates or {}
    now = {case["id"]: case for case in current.get("results", [])}
    result = GateResult()
    for before in baseline.get("results", []):
        if before.get("status") != "ok":
            continue  # it didn't finish then: nothing to hold the current run to
        case_id, limits = before["id"], _limits(gates, before.get("group", ""))
        after = now.get(case_id)
        if after is None:
            result.findings.append(Finding(case_id, "status", "ok", None, "missing"))
            continue
        if after.get("status") != "ok":
            result.findings.append(Finding(case_id, "status", "ok", after.get("status"), "failed"))
            continue
        old, new = before.get("best_s"), after.get("best_s")
        if old is not None and new is not None:
            slower = new > old * (1 + limits["time_tolerance"]) and new - old > limits["time_floor_s"]
            result.findings.append(Finding(case_id, "time", old, new, "slower" if slower else "ok"))
        old_kib, new_kib = before.get("peak_kib"), after.get("peak_kib")
        if old_kib is not None and new_kib is not None:
            heavier = new_kib > old_kib * (1 + limits["memory_tolerance"]) and new_kib - old_kib > limits["memory_floor_kib"]
            result.findings.append(Finding(case_id, "memory", old_kib, new_kib, "more-memory" if heavier else "ok"))
    known = {case["id"] for case in baseline.get("results", [])}
    result.findings += [Finding(case_id, "status", None, case.get("status"), "new") for case_id, case in now.items() if case_id not in known]
    return result


def _shown(value: float | str | None, metric: str) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        return value
    return f"{value:.3f} s" if metric == "time" else f"{value:,.0f} KiB"


def render(result: GateResult, baseline: dict, current: dict) -> str:
    lines = [
        f"# Performance gate: {'passed' if result.passed else 'FAILED'}",
        "",
        f"Baseline: commit {baseline.get('machine', {}).get('git_commit', '?')}, {baseline.get('options', '')}",
        f"Current: commit {current.get('machine', {}).get('git_commit', '?')}, {current.get('options', '')}",
        f"Machine: {current.get('machine', {}).get('cpu', '?')}",
        "",
        "| Case | Metric | Baseline | Current | Change | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for finding in sorted(result.findings, key=lambda finding: (not finding.failed, finding.id, finding.metric)):
        change = ""
        if isinstance(finding.baseline, (int, float)) and isinstance(finding.current, (int, float)) and finding.baseline:
            change = f"{(finding.current / finding.baseline - 1) * 100:+.0f}%"
        lines.append(
            f"| {finding.id} | {finding.metric} | {_shown(finding.baseline, finding.metric)} | {_shown(finding.current, finding.metric)} | {change} | {finding.verdict} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--gates", type=Path, default=DEFAULT_GATES, help="tolerances per group (docs/performance/gates.json)")
    parser.add_argument("--allow-other-machine", action="store_true", help="compare anyway (a look, not a verdict)")
    parser.add_argument("--report", type=Path, help="also write the table as Markdown here")
    args = parser.parse_args(argv)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    current = json.loads(args.current.read_text(encoding="utf-8"))
    gates = json.loads(args.gates.read_text(encoding="utf-8")) if args.gates.exists() else {}
    try:
        result = compare(baseline, current, gates, allow_other_machine=args.allow_other_machine)
    except OtherMachineError as exc:
        print(f"Not compared: {exc}", file=sys.stderr)
        return 2
    report = render(result, baseline, current)
    if args.report:
        args.report.write_text(report + "\n", encoding="utf-8")
    print(report)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
