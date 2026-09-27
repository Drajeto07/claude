# Implementation tracker

`SmartDoc_Master_Implementation_Tracker.xlsx` (repository root) is the control centre for the
production-hardening work. This folder holds the tool that keeps it honest.

| File | Purpose |
|---|---|
| `tracker.py` | Every change to the workbook: tasks, change log, test runs, benchmarks, gates, session state. |
| `seed.py` | The initial task list (audit findings, phases, gates, backlog, plan hypotheses, baseline benchmarks). Used once by `init`. |
| `excel_recalc.py` | Windows + Excel + pywin32: recalculates, stores values, and checks every formula against the raw data. |
| `selftest.py` | Tests the tool on a throwaway workbook. |

Requires `openpyxl` (`excel_recalc.py` also needs `pywin32` and Microsoft Excel).

## Updating

```bash
python tools/tracker/tracker.py set EDIT-001 --status IN_PROGRESS
python tools/tracker/tracker.py set EDIT-001 --status VERIFIED --evidence "frontend/editor/tiptapToDocument.ts" --tests "tiptapMapping.test.ts" --log "Mapped lists inside table cells; Vitest and E2E pass."
python tools/tracker/tracker.py set EDIT-001 --status DONE --commit abc1234
python tools/tracker/tracker.py add EDIT-001A --parent EDIT-001 --title "Lists in table cells"
python tools/tracker/tracker.py log EDIT-001 "Fixed editor serialization for list nodes inside table cells. Added regression test X. E2E passed." --result PASS
python tools/tracker/tracker.py testrun backend "pytest -q" --result PASS --passed 643 --failed 0 --duration 95
python tools/tracker/tracker.py bench BENCH-001 --current 4.2 --threshold 10
python tools/tracker/tracker.py gate GATE-013 --status PASS --evidence "alembic upgrade/check/downgrade/upgrade clean"
python tools/tracker/tracker.py state --touch      # SESSION_STATE <- docs/session-state.json
python tools/tracker/tracker.py show --open --phase 1
```

Rules the tool enforces: statuses and priorities come from fixed lists; `VERIFIED` needs evidence and
tests, `DONE` also needs a commit; `BLOCKED`, `FAILED` and `DEFERRED` need a reason in Notes; IDs are
never reused; change-log entries must say what changed. The tool refuses to write while the workbook
is open in Excel.

## How the workbook is built

`MASTER` and `CHANGE_LOG` are plain tables. The input tables on `CRITICAL_FIXES`, `RELEASE_GATES`,
`PERFORMANCE`, `TESTING`, `BILLING_PLANS`, `PRODUCT_FEATURES` and `SESSION_STATE` are data too. Every
other cell is an Excel formula over `MASTER`, rebuilt by the tool on each write, so a status typed
into `MASTER` in Excel shows up everywhere. Extra columns added to `MASTER` and edits to formula cells
are not kept; extra sheets are.

openpyxl writes formulas without their results, so Excel computes them when the file opens. To store
the values (for other viewers) and verify the formulas:

```bash
python tools/tracker/excel_recalc.py            # any Python with pywin32, on Windows with Excel
```
