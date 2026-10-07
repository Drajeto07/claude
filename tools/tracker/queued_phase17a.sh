#!/usr/bin/env bash
# Tracker updates for TEST-041 (570a2da), DOCS-011 (88f66f3) and INFRA-010 (blocked), queued while
# the workbook was open in Excel (its ~$ lock file present). Run from the repository root once Excel
# has closed it, after the earlier queued_phase*.sh scripts:
#   bash tools/tracker/queued_phase17a.sh
# then excel_recalc.py with a pywin32 Python, commit and push; delete this file in that commit.
set -euo pipefail
if ls ./~\$SmartDoc_Master_Implementation_Tracker.xlsx >/dev/null 2>&1; then
  echo "The tracker is still open in Excel: close it first." >&2
  exit 1
fi
T="backend/venv/Scripts/python.exe tools/tracker/tracker.py"
$T set TEST-041 --status DONE --verified --commit 570a2da --evidence "backend/scripts/perf_gate.py, docs/performance/gates.json, .github/workflows/ci.yml (Performance gate job), docs/performance/README.md + gate-2026-10-07.md; fix in translation/language.py + export/font_resolver.py" --tests "tests/test_perf_gate.py (7), test_multilingual.py fast path; gate run 23b6c56 vs branch: failed (PDF export 500 blocks +66%), fixed, passed (0.377 vs 0.385 s)" --notes "2026-10-07: gates against a same-machine baseline (CI: base and head on one runner); another machine's numbers refused. Found and fixed a real Phase 11 regression." --result PASS
$T set DOCS-011 --status DONE --verified --commit 88f66f3 --evidence "docs/README.md index; docs/{architecture,document-model,docx,pdf,fonts,translation,ai,formatting,security,testing,performance,deployment,billing,operations}" --tests "every index link checked to exist" --notes "2026-10-07: added docs/pdf, docs/deployment, docs/operations (16b) and the index." --result PASS
$T set INFRA-010 --status BLOCKED --notes "2026-10-07: images and the compose stack can't be built or started here (no Docker: virtualization off in this machine's BIOS); CI builds both images on main. A deployment needs Boril's hosting target and accounts. docs/deployment/README.md lists the checks to run on a machine with Docker."
$T log "TEST-041,DOCS-011,INFRA-010" "Phase 17a: performance gates (caught + fixed a PDF export regression), documentation tree; INFRA-010 blocked (no Docker here, no hosting target). Backend 2344 passed/11 skipped." --phase 17 --tests "full backend suite, perf gate run" --result PASS
$T testrun backend "pytest -q" --result PASS --passed 2344 --failed 0 --skipped 11 --commit 570a2da
$T testrun perf-gate "perf_gate.py 23b6c56 vs branch (quick, repeats 3)" --result PASS --passed 98 --failed 0 --commit 570a2da
$T state --touch
echo "Queued Phase 17a tracker updates applied."
