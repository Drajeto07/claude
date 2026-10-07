#!/usr/bin/env bash
# Tracker update for DOCS-010 (95873d8), queued while the workbook was open in Excel (its ~$ lock
# file present). Run from the repository root once Excel has closed it, after the earlier
# queued_phase*.sh scripts:
#   bash tools/tracker/queued_phase18a.sh
# then excel_recalc.py with a pywin32 Python, commit and push; delete this file in that commit.
set -euo pipefail
if ls ./~\$SmartDoc_Master_Implementation_Tracker.xlsx >/dev/null 2>&1; then
  echo "The tracker is still open in Excel: close it first." >&2
  exit 1
fi
T="backend/venv/Scripts/python.exe tools/tracker/tracker.py"
$T set DOCS-010 --status DONE --verified --commit 95873d8 --evidence "docs/final-production-readiness.md (the 16 sections of brief §112), linked from README.md and docs/README.md" --tests "claims checked against the code (capability matrix counts, plans.json, skip reasons, limits) and today's runs: backend 2344/11, Vitest 277, Playwright 49" --notes "2026-10-07: verdict -- code complete for P0/P1; launch needs the owner's decisions and the first Docker start. Release gates: evidence listed per gate; set PASS only from Phase 18's verification run." --result PASS
$T log "DOCS-010" "Final production readiness report written; every P0/P1 task done except INFRA-010 (blocked: no Docker here, no hosting target)." --phase 18 --tests "docs review" --result PASS
$T state --touch
echo "Queued Phase 18a tracker updates applied."
