# SmartDoc 2.0 -- session state (read this first)

**Resume:** read this file, then `SMARTDOC_2_0_TRACKER.json` (tasks), `SMARTDOC_2_0_DECISIONS.md`; check `git status`
and `git log -1` on `feature/smartdoc-2.0`; continue with "Next action". Rebuild the tracker after editing the JSON:
`backend/venv/Scripts/python.exe tools/smartdoc2/build_tracker.py`, then
`<winvenv>/python.exe tools/tracker/excel_recalc.py docs/SMARTDOC_2_0_MASTER_TRACKER.xlsx`.

| | |
| --- | --- |
| Branch | `feature/smartdoc-2.0`; latest code `4f75d19` (Doctor v0 panel) + tracker checkpoint (see `git log -1`) |
| Current phase | P4 E1+E2 VERIFIED (classic default). P9 Doctor v0 prototype built and measured (S2-081 TESTING, behind `?doctor=1`). S2-050 D-012: S1-S5 done, S6-S9 not done (owner) |
| Done this round | isolated PostgreSQL CI workflow (green); D-012 S1, S3 (bucket), S4, S5 (DB marker); PDF right-to-left word order fix (B-021); Doctor v0 core + API + panel + tests |
| Production | unchanged (`4c8fdca`, https://smartdoc-peach.vercel.app); production Supabase only read |
| Preview project (D-012) | `smartdoc-preview` id `ksmwhnnupkrtzrupcitc` -- state and owner steps in `docs/d012-preview/README.md`; not used by any deployment until S6 |
| 2.0 Preview | https://smartdoc-git-feature-smartdoc-20-drajeto.vercel.app (Vercel Authentication) |
| CI | `.github/workflows/isolation-postgres.yml` on every push touching backend/ (throwaway postgres, no secrets); results readable without sign-in as annotations (`scratchpad/gh_runs.py`, `gh_log.py`) |
| Tests (latest) | see the tracker T-027..T-036; Doctor: 72 + 9 backend, 4 e2e + axe |

## Rules carried over (owner)
No merge to main, no promote/Production deployment, no Production configuration change, no deletion or migration of
real user data, no Preview connected to Production by new configuration, no Vercel credential/variable change for
D-012 (S6 refused for now), no paid services, no removal of Vercel Authentication. Never create accounts or sign in on
a deployed site; local throwaway servers only (stop them before a Playwright run: same ports 8100/3100). Never
`python - <<EOF` locally. Docker Desktop doesn't work on the owner's machine: PostgreSQL tests run in GitHub Actions.

## Pending owner decisions / actions
Owner actions: S2 password reset, S3 key pair, upload `docs/d012-preview/identity.json` to `_smartdoc/` in the bucket.
Decisions: S6-S9; real anonymised documents for the Doctor corpus; competitor comparison (cost); 1.x promote; AI provider.

## Next action
Doctor: the two measured gaps as repairs in the file (S2-083: paragraph-level fonts, repeated formatting); B-022
(export rewrites the neighbour of a rewritten table). UI backlog: S2-026 mobile reading, S2-027 compact mobile toolbar,
S2-028 backend messages in BG/EN, S2-023/024/025. E3+ (Free Design) waits for a new priority decision.
Gotchas: route changes need `scripts.export_openapi` + `npm run generate-types` + tests/test_security_suite.py
entries; the app's theme is the `smartdoc_theme` cookie; the E2 shell remembers the open panel (use openPanel in e2e).
