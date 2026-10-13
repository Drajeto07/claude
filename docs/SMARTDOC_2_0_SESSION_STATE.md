# SmartDoc 2.0 -- session state (read this first)

**Resume:** read this file, then `SMARTDOC_2_0_TRACKER.json` (tasks), `SMARTDOC_2_0_DECISIONS.md`; check `git status`
and `git log -1` on `feature/smartdoc-2.0`; continue with "Next action". Rebuild the tracker after editing the JSON:
`backend/venv/Scripts/python.exe tools/smartdoc2/build_tracker.py`, then
`<winvenv>/python.exe tools/tracker/excel_recalc.py docs/SMARTDOC_2_0_MASTER_TRACKER.xlsx`.

| | |
| --- | --- |
| Branch | `feature/smartdoc-2.0` (from `327e22e`), code at `9ed36a6` + tracker checkpoint |
| Current phase | P2 done (VERIFIED locally + preview READY); P3 next |
| Done | P0; P1 (tokens, Inter, primitives, sign-in screens, shell); P2: S2-014 Dashboard, S2-015 New Project (/projects/new), S2-016 BG/EN interface (D-010) |
| Active task | P3 S2-020: Add Content -> Structure Review -> Style -> editor (rebuild of the create wizard on the existing APIs); S2-017 (1.x screens onto the dictionaries) alongside |
| Production | `dpl_HxSobnp5...` (`4c8fdca`), https://smartdoc-peach.vercel.app -- unchanged; 1.x promote candidate `dpl_322ED...` (`f644146`) awaits the owner |
| 2.0 Preview | https://smartdoc-git-feature-smartdoc-20-drajeto.vercel.app (branch alias, newest preview; Vercel Authentication). `9ed36a6` = `dpl_2rXqkcjNs6Ev8c5ngf3BcFXfornz` READY |
| Tests (latest) | Vitest 422; Playwright 64 passed / 1 skipped (incl. e2e/smartdoc2.spec.ts); eslint, tsc, next build; backend unchanged since 2599/11 |

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
P3 / S2-020: audit components/CreateDocumentWizard.tsx (steps, APIs, jobs, e2e helpers that drive it), design the
approved flow (Add content -> analyze -> review/confirm structure -> style -> editor) on the same APIs, keep /new working
for the e2e helpers until the new flow replaces it, all copy in frontend/i18n (EN/BG), tests, local browser check,
commit, push, preview.
