#!/usr/bin/env bash
# Tracker updates for DOCX-015B (deferred) and DOCX-015C (commit 6282fd3), queued while the workbook
# was open in Excel (its ~$ lock file present). Run from the repository root once Excel has closed it,
# after the earlier queued scripts:
#   bash tools/tracker/queued_docx015bc.sh
# then excel_recalc.py with a pywin32 Python, commit and push; delete this file in that commit.
set -euo pipefail
if ls ./~\$SmartDoc_Master_Implementation_Tracker.xlsx >/dev/null 2>&1; then
  echo "The tracker is still open in Excel: close it first." >&2
  exit 1
fi
T="backend/venv/Scripts/python.exe tools/tracker/tracker.py"
$T set DOCX-015B --status DEFERRED --notes "2026-10-07: needs a change of the editor's layout model. The pages are one flat ProseMirror flow laid out by spacer widgets and margin decorations; columns would pull blocks up beside the previous column with negative top margins, which collapse with the blocks' own margins (oscillating layout). Doing it right needs a flex editor root (no margin collapsing) or a wrapper per section -- a risk to every document's layout for a P2. Columns stay kept in both exports and reported."
$T set DOCX-015C --status DONE --verified --commit 6282fd3 --evidence "api/documents.py PUT .../section-text, services/document_service.py set_section_text, models/document.py lastSectionEdited, export/docx_export.py _edited_last_headers; frontend editor/EditorCanvas.tsx (header/footer overlay), sectionHeaders.ts chromeTarget, DocumentEditorShell.tsx chromeEdit; capabilities.py, docs/docx/README.md" --tests "tests/test_sections.py (2 new), sectionHeaders.test.ts (2 new), e2e/section-headers.spec.ts (1 new); 4/4 mutations" --notes "2026-10-07: double-click a page's header/footer to edit it as its section's own (the kind the page shows); Same as previous relinks; last section's main ones stay Page settings'." --result PASS
$T testrun backend "pytest -q" --result PASS --passed 2352 --failed 0 --skipped 11 --commit 6282fd3
$T testrun vitest "npx vitest run" --result PASS --passed 280 --failed 0 --commit 6282fd3
$T testrun playwright "npx playwright test" --result PASS --passed 50 --failed 0 --commit 6282fd3
$T state --touch
echo "Queued DOCX-015B/C tracker updates applied."
