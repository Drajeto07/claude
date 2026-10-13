# SmartDoc 2.0 -- session state (read this first)

**Resume:** read this file, then `SMARTDOC_2_0_TRACKER.json` (tasks), `SMARTDOC_2_0_DECISIONS.md`; check `git status`
and `git log -1` on `feature/smartdoc-2.0`; continue with "Next action". Rebuild the tracker after editing the JSON:
`backend/venv/Scripts/python.exe tools/smartdoc2/build_tracker.py`, then
`<winvenv>/python.exe tools/tracker/excel_recalc.py docs/SMARTDOC_2_0_MASTER_TRACKER.xlsx`.

| | |
| --- | --- |
| Branch | `feature/smartdoc-2.0` (from `327e22e`), last pushed `1003d53` + tracker checkpoint |
| Current phase | P1 done (VERIFIED locally); P2 in progress |
| Done | S2-001..004 (audit, branch, docs, tracker); S2-010 tokens + Inter; S2-011 primitives (Button, TextField, Notice, Logo); S2-012 sign-in screens; S2-013 app shell |
| Active task | S2-014 Dashboard (screen 2) -> S2-015 New Project (screen 3) |
| Production | `dpl_HxSobnp5...` (`4c8fdca`), https://smartdoc-peach.vercel.app -- unchanged; 1.x promote candidate `dpl_322ED...` (`f644146`) awaits the owner |
| 2.0 Preview | https://smartdoc-git-feature-smartdoc-20-drajeto.vercel.app (branch alias, newest preview; Vercel Authentication). `eb69d40` = `dpl_4KbNxArvRLBNuJARviMwh5Mj8bys` READY |
| Tests (latest) | Vitest 378; Playwright full 57 + the 2 fixed specs green; backend unchanged since 2599/11 (no backend change in 2.0 yet) |

## Rules carried over (owner)
No promote, no merge to main, no Production settings, no automation bypass, no destructive data operation, no schema
change without approval. The 2.0 Preview shares the production database and bucket (D-004). Vercel Authentication
stays on: Claude can't open previews; the owner runs browser checks; Claude checks builds and logs (Vercel CLI,
owner's login: `npx --yes vercel@61.1.0 ...` from the home folder; never `vercel curl`, it creates a bypass secret).
Never create accounts or sign in on a deployed site; local throwaway servers only (`tools/dev/throwaway-*.ps1`;
the preview tool reads `Claude - SGD/.claude/launch.json`: smartdoc-backend-throwaway, smartdoc-frontend-throwaway,
smartdoc-backend-throwaway-no-email). Never `python - <<EOF` with `</dev/null` (opens a REPL): write script files.

## Pending owner decisions
D-010 UI language (BG/EN); 1.x promote; SENTRY_DSN; e-mail domain; REL-014 cleanup; separate DB for 2.0 (optional).

## Next action
S2-014 Dashboard: project gallery (cards with a thumbnail area, type, last edited), search over the existing
`listDocuments` API, Create project + Templates + "Create with AI" entries (AI entry honest about what exists), empty /
loading / error states; tests; local browser check; commit; push; check the preview build.
