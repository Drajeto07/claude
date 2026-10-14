# SmartDoc 2.0 -- session state (read this first)

**Resume:** read this file, then `SMARTDOC_2_0_TRACKER.json` (tasks), `SMARTDOC_2_0_DECISIONS.md`; check `git status`
and `git log -1` on `feature/smartdoc-2.0`; continue with "Next action". Rebuild the tracker after editing the JSON:
`backend/venv/Scripts/python.exe tools/smartdoc2/build_tracker.py`, then
`<winvenv>/python.exe tools/tracker/excel_recalc.py docs/SMARTDOC_2_0_MASTER_TRACKER.xlsx`.

| | |
| --- | --- |
| Branch | `feature/smartdoc-2.0` (from `327e22e`); latest code `d8af836` + tracker checkpoint (see `git log -1`) |
| Current phase | P3 done (S2-020/021/022 VERIFIED); S2-017 + S2-R06 VERIFIED; P4 editor: plan E0 written (awaiting owner review), E3 design model foundation done |
| Done | P0; P1; P2 (S2-014, S2-015, S2-016 BG/EN); UI review: S2-018 real thumbnails, S2-R01 light/dark (light default, Settings), S2-R02 dashboard, S2-R03 Translate entry, S2-R04 sidebar, S2-R05; bugs B-006..B-010 |
| Active task | P4 E1: 2.0 editor shell around the current Tiptap canvas, behind `?editor=2` (plan: docs/SMARTDOC_2_0_EDITOR_ARCHITECTURE.md) |
| Production | `dpl_HxSobnp5...` (`4c8fdca`), https://smartdoc-peach.vercel.app -- unchanged; 1.x promote candidate `dpl_322ED...` (`f644146`) awaits the owner |
| 2.0 Preview | https://smartdoc-git-feature-smartdoc-20-drajeto.vercel.app (branch alias, newest preview; Vercel Authentication). `719b8d7` = `dpl_3bYEX4jWjA2UHuRcJqPw8oK1fzKc` READY |
| Tests (latest) | 2026-10-14: Vitest 518 (+ guards: no literal English in 29 screens, no zinc in components/app); tsc; eslint; Playwright 66 / 1 skipped incl. next build; backend 2618 / 11 skipped (no backend change since); browser docs/ui-review/2026-10-14b |

## Rules carried over (owner)
No promote, no merge to main, no Production settings, no automation bypass, no destructive data operation, no schema
change without approval. The 2.0 Preview shares the production database and bucket (D-004). Vercel Authentication
stays on: Claude can't open previews; the owner runs browser checks; Claude checks builds and logs (Vercel CLI,
owner's login: `npx --yes vercel@61.1.0 ...` from the home folder; never `vercel curl`, it creates a bypass secret).
Never create accounts or sign in on a deployed site; local throwaway servers only (`tools/dev/throwaway-*.ps1`;
the preview tool reads `Claude - SGD/.claude/launch.json`: smartdoc-backend-throwaway, smartdoc-frontend-throwaway,
smartdoc-backend-throwaway-no-email). Never `python - <<EOF` with `</dev/null` (opens a REPL): write script files.

## Pending owner decisions
1.x promote; SENTRY_DSN; e-mail domain; REL-014 cleanup; **D-012** (canvas documents vs the shared database -- separate 2.0 DB recommended); review of the editor plan; AI provider (D-007).

## Next action
P4 E1 (after/alongside the owner's review of the editor plan): a 2.0 editor shell around the existing Tiptap canvas behind
`?editor=2` -- top bar (title, save state, undo/redo, zoom, export), rail + left panel (Elements, Pages, Structure,
Templates, History), centred zoomable canvas on white paper, properties panel, status bar; re-house the existing panels;
all copy in en/bg (this is where editor/* moves onto the dictionaries and tokens). Gate: every Vitest + Playwright spec
on both shells. Backlog: B-014 (built-in name contains "(по подразбиране)"). Canvas persistence waits for D-012.
Gotchas: never `python - <<EOF` (REPL hang -- it happened once more today); use the Write tool for scripts with
quotes/Cyrillic (bash heredocs choke); recalc venv = scratchpad/winvenv2.
