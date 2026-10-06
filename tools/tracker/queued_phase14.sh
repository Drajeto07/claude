#!/usr/bin/env bash
# Tracker updates for Phase 14 (REV-002, REV-003, commit ed68af3), queued while the workbook was
# open in Excel (its ~$ lock file present). Run from the repository root once Excel has closed it,
# after queued_phase11/12/13.sh:
#   bash tools/tracker/queued_phase14.sh
# then excel_recalc.py with a pywin32 Python, commit and push; delete this file in that commit.
set -euo pipefail
if ls ./~\$SmartDoc_Master_Implementation_Tracker.xlsx >/dev/null 2>&1; then
  echo "The tracker is still open in Excel: close it first." >&2
  exit 1
fi
T="backend/venv/Scripts/python.exe tools/tracker/tracker.py"
H=ed68af3
E="backend/app/formatting/{engine,proposals}.py, services/document_service.py, api/documents.py proposals/accept; frontend editor/panels/ReviewPanel.tsx, ProposalsList.tsx (ProposalCard, useProposalActions); README.md"
TS="tests/test_review_changes.py (6), test_formatting_engine.py, ReviewPanel.test.tsx (4), e2e/review.spec.ts; 8/8 mutations"
$T set REV-002 --status DONE --verified --commit $H --evidence "$E" --tests "$TS" --notes "2026-10-07: Преглед panel: every waiting change (instruction, translation, health) grouped by the six categories, filter chips, source tags, accept/reject/show, Accept all per category except content." --result PASS
$T set REV-003 --status DONE --verified --commit $H --evidence "$E" --tests "$TS" --notes "2026-10-07: apply_operations refuses insert/delete/move without accepted=True (UnacceptedContentChangeError) -- only proposals.accept sets it; POST .../proposals/accept: one category, one undo step, 422 content_needs_review for content, word-changing proposals of other categories left waiting (translations excepted)." --result PASS
$T finding AUD-05 --notes "Fixed in Phase 2 (AI-005..AI-007: content operations become proposals) and enforced server-side in Phase 14 (REV-003, ed68af3): nothing but accepting a proposal can insert, delete or move content."
$T log "REV-002,REV-003" "Phase 14: Review Changes P0s done (REV-004/005 P2 open); backend 2317 passed/11 skipped, Vitest 276, Playwright 47; 8/8 mutations." --phase 14 --tests "full suites" --result PASS
$T testrun backend "pytest -q" --result PASS --passed 2317 --failed 0 --skipped 11 --commit $H
$T testrun vitest "npx vitest run" --result PASS --passed 276 --failed 0 --commit $H
$T testrun playwright "npx playwright test" --result PASS --passed 47 --failed 0 --commit $H
$T testrun mutations-review "mutate_rev.py" --result PASS --passed 8 --failed 0 --commit $H
$T state --touch
echo "Queued Phase 14 tracker updates applied."
