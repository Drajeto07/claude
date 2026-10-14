# SmartDoc 2.0 -- session state (read this first)

**Resume:** read this file, then `SMARTDOC_2_0_TRACKER.json` (tasks), `SMARTDOC_2_0_DECISIONS.md`; check `git status`
and `git log -1` on `feature/smartdoc-2.0`; continue with "Next action". Rebuild the tracker after editing the JSON:
`backend/venv/Scripts/python.exe tools/smartdoc2/build_tracker.py`, then
`<winvenv>/python.exe tools/tracker/excel_recalc.py docs/SMARTDOC_2_0_MASTER_TRACKER.xlsx`.

| | |
| --- | --- |
| Branch | `feature/smartdoc-2.0` (from `327e22e`); UI review committed after `b716a5f` (see `git log -1`) |
| Current phase | P2 + UI review (2026-10-14) VERIFIED locally; P3 S2-020 in progress |
| Done | P0; P1; P2 (S2-014, S2-015, S2-016 BG/EN); UI review: S2-018 real thumbnails, S2-R01 light/dark (light default, Settings), S2-R02 dashboard, S2-R03 Translate entry, S2-R04 sidebar, S2-R05; bugs B-006..B-010 |
| Active task | P3 S2-020: Add Content -> Structure Review -> Style -> editor (rebuild of the create wizard on the existing APIs); S2-017 (1.x screens onto the dictionaries) alongside |
| Production | `dpl_HxSobnp5...` (`4c8fdca`), https://smartdoc-peach.vercel.app -- unchanged; 1.x promote candidate `dpl_322ED...` (`f644146`) awaits the owner |
| 2.0 Preview | https://smartdoc-git-feature-smartdoc-20-drajeto.vercel.app (branch alias, newest preview; Vercel Authentication). `9ed36a6` = `dpl_2rXqkcjNs6Ev8c5ngf3BcFXfornz` READY |
| Tests (latest) | 2026-10-14: backend full suite (T-013), Vitest 432, tsc, eslint, Playwright 66 passed / 1 skipped incl. next build; browser matrix light/dark x 1280/1440/375 (docs/ui-review/2026-10-14) |

## Rules carried over (owner)
No promote, no merge to main, no Production settings, no automation bypass, no destructive data operation, no schema
change without approval. The 2.0 Preview shares the production database and bucket (D-004). Vercel Authentication
stays on: Claude can't open previews; the owner runs browser checks; Claude checks builds and logs (Vercel CLI,
owner's login: `npx --yes vercel@61.1.0 ...` from the home folder; never `vercel curl`, it creates a bypass secret).
Never create accounts or sign in on a deployed site; local throwaway servers only (`tools/dev/throwaway-*.ps1`;
the preview tool reads `Claude - SGD/.claude/launch.json`: smartdoc-backend-throwaway, smartdoc-frontend-throwaway,
smartdoc-backend-throwaway-no-email). Never `python - <<EOF` with `</dev/null` (opens a REPL): write script files.

## Pending owner decisions
1.x promote; SENTRY_DSN; e-mail domain; REL-014 cleanup; separate DB for 2.0 (optional). (D-010 decided 2026-10-14.)

## Next action
P3 / S2-020 (design: SPEC 5.1). Written, untracked until wired: frontend/components/projects/create/
(structureEdits.ts + test 10 green, ProcessingView, AddContent, StructureReview, ChooseLook, DocumentFlow + test),
frontend/services/api/capabilities.ts (getAiAvailability). Still to do: run scratchpad i18n_create.py equivalent
(`create` section in en.ts/bg.ts), export getAiAvailability from services/api/index.ts, useAiAvailability in
services/queries.ts, app/new/page.tsx -> AppShell + DocumentFlow, e2e helpers.createDocument + documents.spec.ts to the
new wording (Analyse the structure / Confirm the structure / Apply and open the editor / Open without formatting),
vitest, full e2e, browser check light/dark 1280/375, tracker, commit, push, preview.
