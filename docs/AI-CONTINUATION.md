# AI continuation — SmartDoc production hardening

Resume with: **"Прочети docs/AI-CONTINUATION.md и продължи от next task."**

Read in this order: this file → `docs/session-state.json` → `python tools/tracker/tracker.py show --open --phase <current>`
→ the brief section for the current phase in `docs/implementation-brief.md` (§104 lists the phases).
Branch: `feature/smartdoc-production-hardening`. The tracker is `SmartDoc_Master_Implementation_Tracker.xlsx`
(repository root); update it with `tools/tracker/tracker.py` after every atomic task (see `tools/tracker/README.md`).

## CURRENT STATE

- Phase 0 (baseline + tracker + checkpoints): all 11 tasks VERIFIED; the phase commit is next. No production code changed.
- Tracker: 152 tasks across phases 0–18; the 20 audit findings are AUD-01..AUD-20 on `CRITICAL_FIXES`, each linked to the
  tasks that fix it; release gates GATE-001..015 on `RELEASE_GATES`; baseline runs RUN-0001..RUN-0011 on `TESTING`.
- Baseline (details in `docs/architecture/current-baseline.md`): backend 643 passed / 1 skipped; Vitest 46; E2E 16;
  lint, tsc, build clean; migrations clean (head `85211092fe4c`, Supabase 8/8); pip-audit and npm audit clean;
  compose file valid, Docker images not built (daemon not running).

## LAST VERIFIED

- 2026-09-27 — Phase 0 baseline, every check listed above (TESTING RUN-0001..RUN-0011).
- 2026-09-27 — tracker: `python tools/tracker/selftest.py` PASS; `excel_recalc.py` 0 formula errors, 0 value mismatches.

## WHAT WAS CHANGED

- `tools/tracker/` (tracker.py, seed.py, excel_recalc.py, selftest.py, README.md) — new.
- `SmartDoc_Master_Implementation_Tracker.xlsx` — new.
- `docs/AI-CONTINUATION.md`, `docs/session-state.json`, `docs/implementation-brief.md` (the brief, verbatim),
  `docs/architecture/current-baseline.md` — new.
- `.gitignore` — ignores the tracker tool's temporary files.

## WHAT PASSED

- Everything in the baseline (see CURRENT STATE); the tracker's self-test and formula verification.

## WHAT FAILED

- Nothing. Partial: Docker images could not be built (daemon not running) — INFRA-010.

## WHAT REMAINS

- Commit phase 0, then mark its tasks DONE with the commit hash (`tracker.py set <ID> --status DONE --commit <hash>`).
- Phase 1 (editor integrity + content preservation): CORE-001 nested block containers in the model → CORE-002 OpenAPI +
  generated types → CORE-003 backend traversal → EDIT-001..006 editor mapping + save guard → DOCX-001/PDF-001 export of
  nested blocks → FID-001..005 fidelity report → CORE-004 capability matrix → TEST-010 regression tests.
- Phases 2–18 as listed in the tracker.
- Needs Boril (never guess): Stripe account and prices, e-mail provider credentials, Anthropic API key for real-model
  checks, hosting/deployment target.

## NEXT ACTION

- If the phase-0 commit is not in `git log`: run the secret scan, commit, push the branch, then mark INFRA-001..004,
  TEST-001..005, SEC-001, DOCS-001 DONE with the hash.
- Then CORE-001: read `backend/app/models/document.py` and `frontend/editor/tiptapToDocument.ts` (the discard is in
  `inlineFromParagraphs`, lines ~84-92), write the failing tests first, then extend the model.

## IMPORTANT WARNINGS

- Never mark a task VERIFIED/DONE without evidence and tests (the tool refuses anyway). DONE also needs the commit.
- The repository is PUBLIC (github.com/Drajeto07/claude). Run the secret scan before every push; known placeholder hits
  are listed in the auto-memory notes. Never commit `backend/.env`, the user's stress-test DOCX, Office lock files, or any
  password the user pasted in chat.
- Tests must never touch the real Supabase database (`backend/.env` points at it); the test suite enforces this.
- Word fixtures authored on this machine carry Microsoft sensitivity-label (MSIP) properties with the organisation's
  tenant ID in `docProps/custom.xml`: scrub them (and `app.xml` Company) before committing any fixture.
- The FastAPI dev server's auto-reload silently does nothing: restart it after backend edits.
- Close the tracker in Excel before running `tracker.py` (it refuses to write while `~$` lock files exist).
  `excel_recalc.py` needs a Python with pywin32 (e.g. `%TEMP%\sda\Scripts\python.exe`, the audit venv).
- The resume reminder is a session-only cron job (hourly at :23, expires after 7 days); it only fires while this session is
  open and idle. Delete it (CronList + CronDelete) when the brief is finished or only Boril-input items remain.
