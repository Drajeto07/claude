#!/usr/bin/env bash
# Release gates from the Phase 18 verification runs of 2026-10-07 (commit f185825), queued while the
# workbook was open in Excel (its ~$ lock file present). Run from the repository root once Excel has
# closed it, after the earlier queued_phase*.sh scripts:
#   bash tools/tracker/queued_phase18b.sh
# then excel_recalc.py with a pywin32 Python, commit and push; delete this file in that commit.
set -euo pipefail
if ls ./~\$SmartDoc_Master_Implementation_Tracker.xlsx >/dev/null 2>&1; then
  echo "The tracker is still open in Excel: close it first." >&2
  exit 1
fi
T="backend/venv/Scripts/python.exe tools/tracker/tracker.py"
RUNS="2026-10-07: backend 2344 passed/11 skipped (570a2da), Vitest 277, Playwright 49 (f185825)"
$T gate GATE-001 --status PASS --evidence "TEST-022 true-fidelity round trip of every Word fixture, FID-002 content check on every import/export, EDIT-006; Word gate 60/60 identical counts. $RUNS"
$T gate GATE-002 --status PASS --evidence "TEST-030 security suite (-m security) sweeping every route for cross-workspace access, in the full run. $RUNS"
$T gate GATE-003 --status PASS --evidence "AI-004 token-by-token text check, AI-006 proposals, REV-003 apply_operations refuses unaccepted content changes (tests/test_review_changes.py, 8/8 mutations). $RUNS"
$T gate GATE-004 --status NOT_EVALUATED --notes "PLAN-003 race tests pass on SQLite (two real connections); the PostgreSQL variant (-m postgres) runs only in CI's PostgreSQL job, whose result isn't visible here. Set PASS from that run."
$T gate GATE-005 --status PASS --evidence "SEC-010/011/012/013 malformed Word and PDF files, picture and package limits, SVG refused; security suite. $RUNS"
$T gate GATE-006 --status PASS --evidence "Word gate 2026-10-07 (tools/word): 60 files (20 fixtures cleaned, templated into the original, written new) open in Word without repair; every count (open_check + gate_counts) identical to the 2026-10-06 gate; package check none."
$T gate GATE-007 --status PASS --evidence "Every PDF export in the suite read back by two independent parsers (pypdf, pdfminer) and its words checked (fidelity/exports.py); multilingual script matrix (FONT-006). $RUNS"
$T gate GATE-012 --status PASS --evidence "TEST-040: the brief's workflows in 49 Playwright tests against a production build, incl. axe accessibility (f185825)."
$T gate GATE-013 --status NOT_EVALUATED --notes "Locally the models match Alembic head (test_db_migration); upgrade/alembic check/downgrade/upgrade on PostgreSQL runs in CI only (result not visible here). Supabase head was checked after each migration (advisors INFO only)."
$T gate GATE-014 --status PASS --evidence "2026-10-07 dependency audit as CI runs it: pip-audit on both locks and npm audit --omit=dev --audit-level=high -- found werkzeug CVE-2026-102598 (dev), sharp and source-map-js (high); fixed in f185825, both audits clean. Security suite passes; axe: no serious violations."
$T gate GATE-015 --status PASS --evidence "OBS-001 metrics at /api/metrics (Prometheus), OBS-002 request/operation/job ids on every log line, /api/health and /api/ready probes (59cea2a)." --notes "Dashboards and alerts come with a deployment (docs/operations/README.md lists what to alert on)."
$T log "GATE-001..015" "Phase 18 release audit: gates 001-003, 005-012, 014, 015 PASS (008-011 earlier); 004 and 013 need CI's PostgreSQL result. Word gate 60/60 identical; dependency audit found and fixed 3 advisories (f185825)." --phase 18 --tests "Word gate, dependency audit, full suites" --result PASS
$T testrun word-gate "tools/word gate_exports + open_check + gate_counts" --result PASS --passed 60 --failed 0 --commit 904434c
$T testrun dependency-audit "pip-audit (2 locks) + npm audit --omit=dev --audit-level=high" --result PASS --passed 3 --failed 0 --commit f185825
$T testrun vitest "npx vitest run" --result PASS --passed 277 --failed 0 --commit f185825
$T testrun playwright "npx playwright test" --result PASS --passed 49 --failed 0 --commit f185825
$T state --touch
echo "Queued Phase 18b tracker updates applied."
