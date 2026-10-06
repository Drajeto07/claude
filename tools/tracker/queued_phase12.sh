#!/usr/bin/env bash
# Tracker updates for Phase 12 (FMT-001..003, commit fb0e4de), queued while the workbook was open in
# Excel (its ~$ lock file present). Run from the repository root once Excel has closed it, after
# queued_phase11.sh:
#   bash tools/tracker/queued_phase12.sh
# then excel_recalc.py with a pywin32 Python, commit and push; delete this file in that commit.
set -euo pipefail
if ls ./~\$SmartDoc_Master_Implementation_Tracker.xlsx >/dev/null 2>&1; then
  echo "The tracker is still open in Excel: close it first." >&2
  exit 1
fi
T="backend/venv/Scripts/python.exe tools/tracker/tracker.py"
H=fb0e4de
E="backend/app/formatting/{structure,style_preview,reference_style,style_system}.py, ai/semantic_labeling.py, services/{document,template}_service.py, api/documents.py; frontend TemplatesPanel.tsx, ReferenceStyleSummary.tsx; docs/formatting/README.md"
TS="tests/test_format_by_example.py (6), TemplatesPanel.test.tsx (2); 9/9 mutations"
$T set FMT-001 --status DONE --verified --commit $H --evidence "$E" --tests "$TS" --notes "2026-10-07: StyleSystem.structure -- table border, header shading and bold (what most tables share), list levels (most list items), heading numbering; set on the document when the template is applied. Header/footer text belongs to the reference and isn't copied (noted)." --result PASS
$T set FMT-002 --status DONE --verified --commit $H --evidence "$E" --tests "$TS" --notes "2026-10-07: the AI only maps headings; its answer is used only for known ids, levels 1-6, not most paragraphs, and levels that fit the headings' sizes; otherwise headings by look. The engine computes every style." --result PASS
$T set FMT-003 --status DONE --verified --commit $H --evidence "$E" --tests "$TS" --notes "2026-10-07: POST /documents/{id}/style-preview runs the engine on a copy (nothing saved): styles and page now/with the look, changes in words; Templates panel shows Now / With this look before applying or saving." --result PASS
$T log "FMT-001,FMT-002,FMT-003" "Phase 12: Format by Example hardening done; backend 2289 passed/11 skipped, Vitest 269, Playwright 45; 9/9 mutations." --phase 12 --tests "full suites" --result PASS
$T testrun backend "pytest -q" --result PASS --passed 2289 --failed 0 --skipped 11 --commit $H
$T testrun vitest "npx vitest run" --result PASS --passed 269 --failed 0 --commit $H
$T testrun playwright "npx playwright test" --result PASS --passed 45 --failed 0 --commit $H
$T testrun mutations-format-by-example "mutate_fmt.py" --result PASS --passed 9 --failed 0 --commit $H
$T state --touch
echo "Queued Phase 12 tracker updates applied."
