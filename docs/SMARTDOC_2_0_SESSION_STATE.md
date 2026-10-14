# SmartDoc 2.0 -- session state (read this first)

**Resume:** read this file, then `SMARTDOC_2_0_TRACKER.json` (tasks), `SMARTDOC_2_0_DECISIONS.md`; check `git status`
and `git log -1` on `feature/smartdoc-2.0`; continue with "Next action". Rebuild the tracker after editing the JSON:
`backend/venv/Scripts/python.exe tools/smartdoc2/build_tracker.py`, then
`<winvenv>/python.exe tools/tracker/excel_recalc.py docs/SMARTDOC_2_0_MASTER_TRACKER.xlsx`.

| | |
| --- | --- |
| Branch | `feature/smartdoc-2.0` (from `327e22e`); latest code `029acd4` + tracker checkpoint (see `git log -1`) |
| Current phase | P4: E1 + E2 VERIFIED behind `?editor=2` (classic stays default). S2-050 (Preview isolation) plan rev 2 + fail-closed guard in code, BLOCKED on the owner's approval of steps S1-S9. P9 (Reliable Document AI): analysis S2-080 done, Doctor v0 S2-081 backlog |
| Done | P0; P1; P2; P3; S2-017, S2-R06; E1 (S2-030); E2 (S2-031); bugs through B-020 |
| Active task | none open: report to the owner, wait for decisions |
| Production | `dpl_HxSobnp5...` (`4c8fdca`), https://smartdoc-peach.vercel.app -- unchanged; 1.x promote candidate `dpl_322ED...` (`f644146`) awaits the owner |
| 2.0 Preview | https://smartdoc-git-feature-smartdoc-20-drajeto.vercel.app (branch alias; Vercel Authentication). `029acd4` = `dpl_69QAbASgcfiha4vpPyXgpkrkBN6Q` READY |
| Tests (latest) | backend 2647 / 13 skipped (2 of them: PostgreSQL setup-script tests, **not yet run** -- CI runs only on PRs and main; Docker Desktop was off); Vitest 559; tsc; eslint; Playwright 79 / 1 skipped (classic + 13 E2 + axe); screenshots docs/ui-review/2026-10-14d |

## Rules carried over (owner)
No merge to main, no promote/Production deployment, no Production configuration change, no deletion or migration of
real user data, no cloud resource or credential change for D-012, no Free Design documents in the shared database, no
paid AI services or new costs, no bypass of Vercel Authentication -- each needs explicit approval. Claude can't open
previews; the owner runs browser checks; Claude checks builds (Vercel CLI, names only; never `vercel curl`).
Never create accounts or sign in on a deployed site; local throwaway servers only (the preview tool reads
`Claude - SGD/.claude/launch.json`: smartdoc-backend-throwaway, smartdoc-frontend-throwaway). Those servers use ports
8100/3100 like Playwright: stop them before a Playwright run. Never `python - <<EOF`: write script files.

## Pending owner decisions
D-012 steps S1-S9 (plan section 9); whether CI may run on this branch (a draft pull request, not a merge) or Docker
Desktop may be started locally, to run the 2 PostgreSQL tests; Doctor v0 go-ahead and its open questions; 1.x
promote; SENTRY_DSN; e-mail domain; AI provider (D-007).

## Next action
After the owner's answers: (1) run the 2 PostgreSQL tests (CI or local Docker) before any D-012 step; (2) D-012 steps as
approved; (3) E3 per the editor architecture plan, or S2-023/024/025 (owner's UI backlog); (4) Doctor v0 only with
approval. Known E2 gaps: Health check texts and version descriptions come from the server in English (needs message
codes); the classic shell's rail labels are Bulgarian-only until E2 replaces the classic shell.
Gotchas: route/health changes need `scripts.export_openapi` + `npm run generate-types`; id-taking routes go into
tests/test_security_suite.py; Write tool for scripts with quotes/Cyrillic; recalc venv = scratchpad/winvenv2; the
repo isn't prettier-formatted; screenshots: scratchpad/shots_e2.js (Edge headless, sets the smartdoc_theme cookie --
the app ignores the OS theme); the grey box top-left in local shots is Next.js's dev overlay, not the product.
