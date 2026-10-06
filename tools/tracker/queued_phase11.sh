#!/usr/bin/env bash
# Tracker updates for Phase 11 (FONT-001..004, FONT-006, commit ad6887f), queued while the workbook
# was open in Excel (its ~$ lock file present). Run from the repository root once Excel has closed it:
#   bash tools/tracker/queued_phase11.sh
# then excel_recalc.py with a pywin32 Python, commit and push; delete this file in that commit.
set -euo pipefail
if ls ./~\$SmartDoc_Master_Implementation_Tracker.xlsx >/dev/null 2>&1; then
  echo "The tracker is still open in Excel: close it first." >&2
  exit 1
fi
T="backend/venv/Scripts/python.exe tools/tracker/tracker.py"
H=ad6887f
E="backend/app/export/{font_catalogue,font_resolver,rtl}.py, app/bidi.py, pdf_export.py, docx_export.py, fidelity/exports.py; docs/fonts/README.md"
TS="tests/test_multilingual.py (29), test_export_fidelity.py, expected-loss manifests; 11/11 mutations"
$T set FONT-001 --status DONE --verified --commit $H --evidence "$E" --tests "$TS" --notes "2026-10-07: fontTools catalogue -- coverage by script, metrics, embeddability (fsType 2 never embedded)." --result PASS
$T set FONT-002 --status DONE --verified --commit $H --evidence "$E" --tests "$TS" --notes "2026-10-07: deterministic resolver (no AI): script runs, the paragraph's font by letters, script chains, symbol fallback, missing named." --result PASS
$T set FONT-003 --status DONE --verified --commit $H --evidence "$E" --tests "$TS" --notes "2026-10-07: HarfBuzz shaping; own UAX#9 bidi as reportlab's rlbidi; RtlParagraph orders lines right to left; notes for undrawable characters and Devanagari/Thai text layer; read-back via pdfminer for RTL documents." --result PASS
$T set FONT-004 --status DONE --verified --commit $H --evidence "$E" --tests "$TS" --notes "2026-10-07: w:rFonts eastAsia/cs, w:lang eastAsia/bidi, w:rtl, w:bCs/w:iCs, w:bidi on RTL-led paragraphs." --result PASS
$T set FONT-006 --status DONE --verified --commit $H --evidence "$E" --tests "$TS" --notes "2026-10-07: script matrix x PDF (on the machine's fonts; uncovered scripts expected to be reported) and Word XML; bidi checked against python-bidi." --result PASS
$T gate GATE-008 --status PASS --evidence "FONT-003/006: tests/test_multilingual.py script matrix, test_arabic_is_shaped_and_right_to_left_text_is_laid_out_and_aligned_right_to_left" --notes "2026-10-07: on fonts installed where the PDF is made; production images need fonts-noto-core/cjk for Devanagari, Thai, CJK (docs/fonts/README.md)."
$T log "FONT-001,FONT-002,FONT-003,FONT-004,FONT-006" "Phase 11 gate: P0/P1 done (FONT-005 P2 open); backend 2279 passed/11 skipped, Vitest 267, Playwright 45; 11/11 mutations." --phase 11 --tests "full suites" --result PASS
$T testrun backend "pytest -q" --result PASS --passed 2279 --failed 0 --skipped 11 --commit $H
$T testrun vitest "npx vitest run" --result PASS --passed 267 --failed 0 --commit $H
$T testrun playwright "npx playwright test" --result PASS --passed 45 --failed 0 --commit $H
$T testrun mutations-fonts "mutate_fonts.py" --result PASS --passed 11 --failed 0 --commit $H
$T state --touch
echo "Queued Phase 11 tracker updates applied."
