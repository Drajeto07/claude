# SmartDoc 2.0 -- session state (read this first)

**Resume:** read this file, then `SMARTDOC_2_0_TRACKER.json`, `SMARTDOC_2_0_DECISIONS.md`, `docs/d012-preview/S6_PROCEDURE.md`;
check `git status` / `git log -3` on `feature/smartdoc-2.0`; continue with "Next action". Don't redo finished work.
Tracker: `backend/venv/Scripts/python.exe tools/smartdoc2/build_tracker.py`, then
`<scratchpad>/winvenv2/Scripts/python.exe tools/tracker/excel_recalc.py docs/SMARTDOC_2_0_MASTER_TRACKER.xlsx`.

## Checkpoint 2026-10-15 (after the D-012 user test)

| | |
| --- | --- |
| Branch | `feature/smartdoc-2.0`. Remote tip `3489a6a` = the S7 deployment. Local commits after it: diagnostics (`Isolation refusals say why, safely...`) + this checkpoint -- see `git log origin/feature/smartdoc-2.0..HEAD` |
| D-012 | **S1-S6 done, S7 switched and technically verified, NOT VERIFIED**: the owner's user test failed on **B-027** (false "changed in another tab or window" while typing in one tab). S8, S9 not approved |
| B-027 (High) | Cause: Vercel's edge evaluates the standard `If-Match` header against its own ETag and turned successful saves (app 200, revision bumped) into 412 at the browser; the client never learned the new revision, so the next save was a real 412. Proof: Preview logs (app 200 vs edge 412 on the same PATCHes) + pg_stat_statements (every document UPDATE hit its row). Fix **local, not pushed**: revision sent in our own `X-SmartDoc-Revision` header (backend reads it first, still accepts If-Match; version check / 409 / 412 / 428 unchanged). Regression: `frontend/e2e/autosave-conflict.spec.ts` (emulated edge; fails with the owner's exact message without the fix) |
| B-026 (Low) | "Saved" shown during the 1.2 s autosave delay; new `pending` status "Not saved yet" / „Още не е запазено" -- local, not pushed |
| Production and B-027 | Same client code path. Production's runtime logs reach back only ~1.5 min (Hobby retention), so there is **no evidence either way** of production users hit. A production fix needs the owner's separate approval (merge/promote) |
| 2.0 Preview | `dpl_3262fjM25cveZESWDNfkoBZF6csr` READY, https://smartdoc-git-feature-smartdoc-20-drajeto.vercel.app -- on Supabase project `smartdoc-preview` (`ksmwhnnupkrtzrupcitc`) and bucket `smartdoc-preview-files` |
| Proof of S7 | health (owner): `ok / preview / pinned yes / d8b55a9be8 / verified`. Independent (new project's logs): 10:38:17 Supavisor `Connection authenticated`; marker read once by `postgres` (pg_stat_statements); Storage `GET 200 /s3/smartdoc-preview-files/_smartdoc/identity.json` by `Boto3/1.43.101`. Before the fix: 9 x `password authentication failed` (wrong password in the branch DATABASE_URL; the guard refused correctly) |
| Production | unchanged: only read. No connections or storage access after 10:12:17 (before the S7 push); 2 users / 11 documents / 4 files, newest from 2026-10-13 |
| CI | `isolation-postgres.yml` green on 3489a6a (run 38718605753: isolation 75, PostgreSQL 14). Temporary branch `ci-only-d012-pin` (no Vercel deployment, `git.deploymentEnabled`) still on GitHub -- delete when D-012 is VERIFIED |
| Tests | on the B-027/B-026 fix: backend 2809 passed / 16 skipped (PostgreSQL ones run in CI); Vitest 561; Playwright 90 passed / 1 skipped (incl. `autosave-conflict.spec.ts` 6); tsc + eslint clean |
| Doctor v0 | prototype behind `?doctor=1` (S2-081 TESTING); measured 15/23 planted defects, 0 wrong proposals; gaps S2-083 |

## Rules carried over (owner)
No merge to main, no promote/Production deployment, no Production change, no deletion or move of user data, no
further Vercel/Supabase credential changes, no removal of Vercel Authentication, no paid services. S8 and S9 need
separate approval. Never create accounts or sign in on a deployed site (the owner runs the user test). Never print
secrets; Vercel env read = names/targets/branch/type only (`scratchpad/s6_check.py`, `vproj.py env`). Every push to
`feature/smartdoc-2.0` is a Preview deployment on the isolated project: push only verified, approved work.

## Next action
0. Owner approves the push of the local commits (diagnostics, checkpoint, B-027/B-026 fix) -> secret scan -> push ->
   new Preview deployment -> health check (owner) -> owner repeats the user test (steps in the B-027 report: type in
   bursts, reload, more typing, export; optional second-tab check). Only after a passing repeat: D-012 VERIFIED.
1. Owner's user test on the Preview (synthetic account `preview-check-<date>@example.com`, DOCX with a picture, edit,
   save, reload, DOCX/PDF export). Then, read-only: the account/document/files exist in `smartdoc-preview` and not in
   production (counts by that address and by time). Then mark D-012 VERIFIED (tracker S2-050, D-012, roadmap P8),
   delete the `ci-only-d012-pin` branch on GitHub.
2. Then Document Doctor + SafeEdit (S2-083 gaps, B-022), keeping the editor and the roadmap.
