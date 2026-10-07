#!/usr/bin/env bash
# Tracker updates for Phase 16a (FEAT-010, FEAT-011, commit 21611e8), queued while the workbook was
# open in Excel (its ~$ lock file present). Run from the repository root once Excel has closed it,
# after queued_phase11..14.sh:
#   bash tools/tracker/queued_phase16a.sh
# then excel_recalc.py with a pywin32 Python, commit and push; delete this file in that commit.
set -euo pipefail
if ls ./~\$SmartDoc_Master_Implementation_Tracker.xlsx >/dev/null 2>&1; then
  echo "The tracker is still open in Excel: close it first." >&2
  exit 1
fi
T="backend/venv/Scripts/python.exe tools/tracker/tracker.py"
H=21611e8
$T set FEAT-010 --status DONE --verified --commit $H --evidence "backend/app/formatting/accessibility.py, api/documents.py GET .../accessibility; frontend HealthPanel.tsx Accessibility section; README.md" --tests "tests/test_accessibility.py (11), HealthPanel.test.tsx; 11/11 mutations" --notes "2026-10-07: heading hierarchy, alt text, link labels (runs joined), table headers, reading order (floating pictures/tables), language set + others marked, WCAG 2.2 AA contrast vs highlights and cell shading. No score, no AI." --result PASS
$T set FEAT-011 --status DONE --verified --commit $H --evidence "frontend e2e/accessibility.spec.ts (axe-core 4.13.0, WCAG 2.x A/AA); fixes in DocumentEditorShell (textbox name), SidePanel (focusable region), Dashboard (<dl>), HealthPanel (no opacity), zinc-400 -> zinc-500 small text, amber-700 buttons" --tests "e2e/accessibility.spec.ts (2): signed-out pages, dashboard, documents, new, templates, account, billing, editor + 4 panels: zero serious/critical" --notes "2026-10-07: zero serious or critical axe violations on the main pages and the editor (light theme)." --result PASS
$T log "FEAT-010,FEAT-011" "Phase 16a: accessibility checker + axe-clean app; backend 2331 passed/11 skipped, Vitest 277, Playwright 49; 11/11 mutations." --phase 16 --tests "full suites" --result PASS
$T testrun backend "pytest -q" --result PASS --passed 2331 --failed 0 --skipped 11 --commit $H
$T testrun vitest "npx vitest run" --result PASS --passed 277 --failed 0 --commit $H
$T testrun playwright "npx playwright test" --result PASS --passed 49 --failed 0 --commit $H
$T testrun mutations-accessibility "mutate_a11y.py" --result PASS --passed 11 --failed 0 --commit $H
$T state --touch
echo "Queued Phase 16a tracker updates applied."
