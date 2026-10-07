#!/usr/bin/env bash
# Tracker update for DOCX-015A (commit 4a3c2ca), queued while the workbook was open in Excel (its ~$ lock
# file present). Run from the repository root once Excel has closed it, after the queued_phase*.sh scripts:
#   bash tools/tracker/queued_docx015a.sh
# then excel_recalc.py with a pywin32 Python, commit and push; delete this file in that commit.
set -euo pipefail
if ls ./~\.xlsx >/dev/null 2>&1; then
  echo "The tracker is still open in Excel: close it first." >&2
  exit 1
fi
T="backend/venv/Scripts/python.exe tools/tracker/tracker.py"
$T set DOCX-015A --status DONE --verified --commit 4a3c2ca --evidence "parsers/docx.py _last_section, parsers/docx_styles.py + docx_inline.py (docx.page_setup.size), formatting/engine.py _drop_custom_page_size, export/docx_export.py _section_layout, frontend editor/sectionPages.ts basePage; capabilities.py; docs/docx/README.md" --tests "tests/test_sections.py (2 new), sectionPages.test.ts; 4/4 mutations" --notes "2026-10-07: kept on the pages here and in both exports; a size or orientation chosen here (above the source tier) replaces it." --result PASS
$T testrun backend "pytest -q" --result PASS --passed 2346 --failed 0 --skipped 11 --commit 4a3c2ca
$T testrun vitest "npx vitest run" --result PASS --passed 278 --failed 0 --commit 4a3c2ca
$T testrun playwright "npx playwright test" --result PASS --passed 49 --failed 0 --commit 4a3c2ca
$T state --touch
echo "Queued DOCX-015A tracker update applied."
