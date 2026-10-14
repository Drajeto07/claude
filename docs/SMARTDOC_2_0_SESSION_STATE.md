# SmartDoc 2.0 -- session state (read this first)

**Resume:** read this file, then `SMARTDOC_2_0_TRACKER.json` (tasks), `SMARTDOC_2_0_DECISIONS.md`; check `git status`
and `git log -1` on `feature/smartdoc-2.0`; continue with "Next action". Rebuild the tracker after editing the JSON:
`backend/venv/Scripts/python.exe tools/smartdoc2/build_tracker.py`, then
`<winvenv>/python.exe tools/tracker/excel_recalc.py docs/SMARTDOC_2_0_MASTER_TRACKER.xlsx`.

| | |
| --- | --- |
| Branch | `feature/smartdoc-2.0` (from `327e22e`); latest code `b85cc79` + tracker checkpoint (see `git log -1`) |
| Current phase | P4: E1 editor shell VERIFIED behind `?editor=2` (classic stays default); P3, S2-017, S2-R06 done; S2-050 (Preview isolation) planned, BLOCKED on the owner's approval |
| Done | P0; P1; P2 (S2-014, S2-015, S2-016 BG/EN); UI review: S2-018 real thumbnails, S2-R01 light/dark (light default, Settings), S2-R02 dashboard, S2-R03 Translate entry, S2-R04 sidebar, S2-R05; bugs B-006..B-010 |
| Active task | E2: selection model + command registry + contextual toolbar in Document Mode; editor/* panels onto the dictionaries and tokens |
| Production | `dpl_HxSobnp5...` (`4c8fdca`), https://smartdoc-peach.vercel.app -- unchanged; 1.x promote candidate `dpl_322ED...` (`f644146`) awaits the owner |
| 2.0 Preview | https://smartdoc-git-feature-smartdoc-20-drajeto.vercel.app (branch alias, newest preview; Vercel Authentication). `719b8d7` = `dpl_3bYEX4jWjA2UHuRcJqPw8oK1fzKc` READY |
| Tests (latest) | 2026-10-14: backend 2625 / 11 skipped; Vitest 520; tsc; eslint; Playwright 74 / 1 skipped (66 classic + 8 editor-v2, axe on the 2.0 shell light/dark) incl. next build; browser docs/ui-review/2026-10-14c |

## Rules carried over (owner)
No promote, no merge to main, no Production settings, no automation bypass, no destructive data operation, no schema
change without approval. The 2.0 Preview shares the production database and bucket (D-004). Vercel Authentication
stays on: Claude can't open previews; the owner runs browser checks; Claude checks builds and logs (Vercel CLI,
owner's login: `npx --yes vercel@61.1.0 ...` from the home folder; never `vercel curl`, it creates a bypass secret).
Never create accounts or sign in on a deployed site; local throwaway servers only (`tools/dev/throwaway-*.ps1`;
the preview tool reads `Claude - SGD/.claude/launch.json`: smartdoc-backend-throwaway, smartdoc-frontend-throwaway,
smartdoc-backend-throwaway-no-email). Never `python - <<EOF` with `</dev/null` (opens a REPL): write script files.

## Pending owner decisions
**Approval of the Preview isolation switch** (docs/SMARTDOC_2_0_PREVIEW_ISOLATION_PLAN.md -- the owner creates the Supabase project's keys and enters branch-scoped Vercel variables); 1.x promote; SENTRY_DSN; e-mail domain; REL-014 cleanup; AI provider (D-007).

## Next action
E2 (behind `?editor=2`): one selection model for Document Mode (block / text / picture / table), a command registry
(toolbar, properties panel and shortcuts read it), the contextual toolbar per selection type, and the reused editor/*
panels (structure, templates, instructions, translate, review, page, history, health, check, properties, status and
action bars) onto the dictionaries and the theme tokens. Gate: every Playwright spec on both shells + axe.
Backlog from the owner's review: S2-023 (look step on phones), S2-024 (tables in the structure check), S2-025
(Projects as a gallery). After the owner approves S2-050: follow the plan's steps 1-7 (owner enters secrets).
Gotchas: route/health changes need `scripts.export_openapi` + `npm run generate-types` (contract test); id-taking
routes go into tests/test_security_suite.py; never `python - <<EOF`; Write tool for scripts with quotes/Cyrillic;
recalc venv = scratchpad/winvenv2; the repo isn't prettier-formatted (don't run prettier with defaults).
