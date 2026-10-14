# SmartDoc 2.0 -- session state (read this first)

**Resume:** read this file, then `SMARTDOC_2_0_TRACKER.json` (tasks), `SMARTDOC_2_0_DECISIONS.md`; check `git status`
and `git log -1` on `feature/smartdoc-2.0`; continue with "Next action". Rebuild the tracker after editing the JSON:
`backend/venv/Scripts/python.exe tools/smartdoc2/build_tracker.py`, then
`<winvenv>/python.exe tools/tracker/excel_recalc.py docs/SMARTDOC_2_0_MASTER_TRACKER.xlsx`.

| | |
| --- | --- |
| Branch | `feature/smartdoc-2.0` (from `327e22e`); UI review `719b8d7`, P3 document flow after it (see `git log -1`) |
| Current phase | P3: S2-020 document flow VERIFIED locally; M3.3 style recommendation + S2-017 next |
| Done | P0; P1; P2 (S2-014, S2-015, S2-016 BG/EN); UI review: S2-018 real thumbnails, S2-R01 light/dark (light default, Settings), S2-R02 dashboard, S2-R03 Translate entry, S2-R04 sidebar, S2-R05; bugs B-006..B-010 |
| Active task | S2-017 (1.x screens and the flow's 1.x pieces onto the dictionaries) with S2-R06 (theme tokens), then M3.3 |
| Production | `dpl_HxSobnp5...` (`4c8fdca`), https://smartdoc-peach.vercel.app -- unchanged; 1.x promote candidate `dpl_322ED...` (`f644146`) awaits the owner |
| 2.0 Preview | https://smartdoc-git-feature-smartdoc-20-drajeto.vercel.app (branch alias, newest preview; Vercel Authentication). `719b8d7` = `dpl_3bYEX4jWjA2UHuRcJqPw8oK1fzKc` READY |
| Tests (latest) | 2026-10-14: backend 2618 passed / 11 skipped; Vitest 452; tsc, eslint; Playwright 66 / 1 skipped on the new flow (incl. next build); browser checks in docs/ui-review/2026-10-14 |

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
S2-017: move the remaining 1.x screens onto the dictionaries -- first the pieces the new flow shows in English
(TrackedChangesChoice, ReferenceStyleSummary, JobProgressBar, TemplatePreviewSample text), then account settings,
documents list, templates, billing, editor chrome -- together with S2-R06 (zinc classes -> theme tokens), screen by
screen with EN/BG tests and a grep test for hard-coded English. Then P3 M3.3 (style recommendation from the
structure; deterministic first, AI only when configured -- D-007). Recalc venv for the tracker: scratchpad/winvenv2
(the old winvenv was damaged by a temp cleanup).
