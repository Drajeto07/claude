"""CI only: a JUnit result as the run's summary and as annotations.

    python -m scripts.ci_test_report isolation.xml postgres.xml

The summary (GITHUB_STEP_SUMMARY) lists every test; the annotations -- which GitHub shows to anyone who can see
the repository, without signing in -- carry the totals and each failure with its message, so a run's outcome can
be read from the public API. Test names and assertion messages only: the tests use no secrets.
"""

import os
import pathlib
import sys
import xml.etree.ElementTree as ET

_LIMIT = 900


def _escape(text: str) -> str:
    # Workflow-command escaping: %, CR and LF.
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def report(paths: list[str]) -> tuple[list[str], list[str]]:
    summary: list[str] = []
    commands: list[str] = []
    for name in paths:
        path = pathlib.Path(name)
        if not path.exists():
            summary.append(f"### {name}: not produced\n")
            commands.append(f"::error title={name}::not produced (the step before it did not run)")
            continue
        root = ET.parse(path).getroot()
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        total = int(suite.get("tests", 0))
        failed = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
        skipped = int(suite.get("skipped", 0))
        line = f"{name}: {total - failed - skipped} passed, {failed} failed, {skipped} skipped"
        summary.append(f"### {line}\n")
        commands.append(f"::notice title=Test results::{_escape(line)}")
        for case in suite.iter("testcase"):
            problem = case.find("failure")
            if problem is None:
                problem = case.find("error")
            state = "FAILED" if problem is not None else "skipped" if case.find("skipped") is not None else "passed"
            summary.append(f"- {state}: `{case.get('classname')}::{case.get('name')}`")
            if problem is not None:
                message = (problem.get("message") or "") + "\n" + (problem.text or "")[-_LIMIT:]
                commands.append(f"::error title={case.get('name')}::{_escape(message.strip()[:_LIMIT])}")
        summary.append("")
    return summary, commands


def main(argv: list[str]) -> int:
    summary, commands = report(argv)
    if target := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("\n".join(summary) + "\n")
    print("\n".join(commands))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
