# SmartDoc 2.0 -- session state (read this first)

**Resume:** read this file, then `SMARTDOC_2_0_TRACKER.json` (tasks), `SMARTDOC_2_0_DECISIONS.md`; check `git status`
and `git log -1` on `feature/smartdoc-2.0`; continue with "Next action". Rebuild the tracker after editing the JSON:
`backend/venv/Scripts/python.exe tools/smartdoc2/build_tracker.py`, then
`<winvenv>/python.exe tools/tracker/excel_recalc.py docs/SMARTDOC_2_0_MASTER_TRACKER.xlsx`.

| | |
| --- | --- |
| Branch | `feature/smartdoc-2.0` (from `327e22e`) |
| Current phase | P0 -> P1 |
| Active task | S2-010 / S2-011 / S2-012 (milestone M1: tokens, primitives, Login/Registration) |
| Production | `dpl_HxSobnp5...` (`4c8fdca`), https://smartdoc-peach.vercel.app -- unchanged; 1.x promote candidate `dpl_322ED...` (`f644146`) awaits the owner |
| 2.0 Preview | the branch's previews (alias appears after the first push) |
| Tests (baseline) | backend 2599/11, Vitest 368, Playwright 59/1 (local) |

## Rules carried over (owner)
No promote, no merge to main, no Production settings, no automation bypass, no destructive data operation, no schema
change without approval. The 2.0 Preview shares the production database and bucket (D-004). Vercel Authentication
stays on: Claude can't open previews; the owner runs browser checks; Claude checks builds and logs (Vercel CLI,
owner's login: `npx --yes vercel@61.1.0 ...` from the home folder; never `vercel curl`, it creates a bypass secret).
Never create accounts or sign in on a deployed site; local throwaway servers only (`tools/dev/throwaway-*.ps1`).

## Pending owner decisions
D-010 UI language; 1.x promote; SENTRY_DSN; e-mail domain; REL-014 cleanup; separate DB for 2.0 (optional).

## Next action
Implement M1 (S2-010 tokens + Inter, S2-011 primitives, S2-012 Login/Registration), run Vitest/tsc/eslint/build and
Playwright auth specs, check the screens on the throwaway local servers, commit, push, check the preview build.
