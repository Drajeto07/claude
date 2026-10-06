#!/usr/bin/env bash
# Tracker updates for Phase 13 (HLTH-001, HLTH-002, commit d673602), queued while the workbook was
# open in Excel (its ~$ lock file present). Run from the repository root once Excel has closed it,
# after queued_phase11.sh and queued_phase12.sh:
#   bash tools/tracker/queued_phase13.sh
# then excel_recalc.py with a pywin32 Python, commit and push; delete this file in that commit.
set -euo pipefail
if ls ./~\$SmartDoc_Master_Implementation_Tracker.xlsx >/dev/null 2>&1; then
  echo "The tracker is still open in Excel: close it first." >&2
  exit 1
fi
T="backend/venv/Scripts/python.exe tools/tracker/tracker.py"
H=d673602
E="backend/app/formatting/{health,health_fixes,proposals}.py, models/document.py (ProposedChange health), api/documents.py health/fixes; frontend HealthPanel.tsx, ProposalsList.tsx, EditorStatusBar.tsx; README.md"
TS="tests/test_health_2.py (15), test_health.py, HealthPanel.test.tsx (2), documents.test.ts, e2e/health.spec.ts; 12/12 mutations"
$T set HLTH-001 --status DONE --verified --commit $H --evidence "$E" --tests "$TS" --notes "2026-10-07: +9 checks: alt text, hidden text, another language not marked, not kept from the import, sections almost alike / other paper, broken lists, empty paragraphs, too wide for the text, formatting repeated from the style (broken links existed)." --result PASS
$T set HLTH-002 --status DONE --verified --commit $H --evidence "$E" --tests "$TS" --notes "2026-10-07: POST .../health/fixes -> ProposedChange source=health with before/after; accepted only for the block as checked (fingerprint), one undoable step; stale fixes dropped on save; no fix for alt text or hidden text. E2E found and fixed a missed revision record (documentWrite)." --result PASS
$T log "HLTH-001,HLTH-002" "Phase 13: Document Health 2.0 P1s done (HLTH-003 P2 open); backend 2308 passed/11 skipped, Vitest 272, Playwright 46; 12/12 mutations." --phase 13 --tests "full suites" --result PASS
$T testrun backend "pytest -q" --result PASS --passed 2308 --failed 0 --skipped 11 --commit $H
$T testrun vitest "npx vitest run" --result PASS --passed 272 --failed 0 --commit $H
$T testrun playwright "npx playwright test" --result PASS --passed 46 --failed 0 --commit $H
$T testrun mutations-health "mutate_hlth.py" --result PASS --passed 12 --failed 0 --commit $H
$T state --touch
echo "Queued Phase 13 tracker updates applied."
