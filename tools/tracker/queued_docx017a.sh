#!/usr/bin/env bash
# Tracker update for DOCX-017A (commit b7573d6), queued while the workbook was open in Excel (its ~$
# lock file present). Run from the repository root once Excel has closed it, after the earlier queued scripts:
#   bash tools/tracker/queued_docx017a.sh
# then excel_recalc.py with a pywin32 Python, commit and push; delete this file in that commit.
set -euo pipefail
if ls ./~\$SmartDoc_Master_Implementation_Tracker.xlsx >/dev/null 2>&1; then
  echo "The tracker is still open in Excel: close it first." >&2
  exit 1
fi
T="backend/venv/Scripts/python.exe tools/tracker/tracker.py"
$T set DOCX-017A --status DONE --verified --commit b7573d6 --evidence "parsers/docx_tables.py (PositionLook, StyleLook.conditionals, position_look), parsers/docx.py (_styled_run), capabilities.py, docs/docx/README.md; golden 16-table-engine" --tests "tests/test_docx_tables.py (3 new + header test), 6/6 mutations" --notes "2026-10-07: conditional formats resolved per cell in Word's order from tblLook, band sizes kept; own shading/run formatting win; borders by position still reported." --result PASS
$T testrun backend "pytest -q" --result PASS --passed 2355 --failed 0 --skipped 11 --commit b7573d6
$T testrun vitest "npx vitest run" --result PASS --passed 280 --failed 0 --commit b7573d6
$T testrun playwright "npx playwright test" --result PASS --passed 50 --failed 0 --commit b7573d6
$T state --touch
echo "Queued DOCX-017A tracker update applied."
