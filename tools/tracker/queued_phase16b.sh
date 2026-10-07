#!/usr/bin/env bash
# Tracker updates for Phase 16b (OBS-001, OBS-002, commit 59cea2a), queued while the workbook was
# open in Excel (its ~$ lock file present). Run from the repository root once Excel has closed it,
# after queued_phase11..14 and 16a:
#   bash tools/tracker/queued_phase16b.sh
# then excel_recalc.py with a pywin32 Python, commit and push; delete this file in that commit.
set -euo pipefail
if ls ./~\$SmartDoc_Master_Implementation_Tracker.xlsx >/dev/null 2>&1; then
  echo "The tracker is still open in Excel: close it first." >&2
  exit 1
fi
T="backend/venv/Scripts/python.exe tools/tracker/tracker.py"
H=59cea2a
E="backend/app/observability.py, main.py (/api/metrics, middleware), logging_setup.py, jobs/runner.py, services/job_service.py, ai/budget.py; docs/operations/README.md"
TS="tests/test_metrics.py (5), test_jobs.py; 11/11 mutations"
$T set OBS-001 --status DONE --verified --commit $H --evidence "$E" --tests "$TS" --notes "2026-10-07: Prometheus text at GET /api/metrics (METRICS_TOKEN bearer only; 404 unset): HTTP requests/latency by route template and status class, jobs by type/outcome + duration, AI calls by outcome + latency, exports by format/path/outcome. No ids, paths or text in labels." --result PASS
$T set OBS-002 --status DONE --verified --commit $H --evidence "$E" --tests "$TS" --notes "2026-10-07: request_id, operation_id (the request that started it, carried by its jobs via payload.operationId) and job_id on every log line (ContextFilter)." --result PASS
$T log "OBS-001,OBS-002" "Phase 16b: metrics + ids in logs; backend 2336 passed/11 skipped, Playwright 48 + 1 flaky (kept-blocks, 6/6 on rerun); 11/11 mutations." --phase 16 --tests "full suites" --result PASS
$T testrun backend "pytest -q" --result PASS --passed 2336 --failed 0 --skipped 11 --commit $H
$T testrun playwright "npx playwright test" --result PASS --passed 49 --failed 0 --commit $H
$T testrun mutations-observability "mutate_obs.py" --result PASS --passed 11 --failed 0 --commit $H
$T state --touch
echo "Queued Phase 16b tracker updates applied."
