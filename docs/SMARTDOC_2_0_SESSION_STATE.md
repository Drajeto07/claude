# SmartDoc 2.0 -- session state (read this first)

**Resume:** read this file, then `SMARTDOC_2_0_TRACKER.json`, `SMARTDOC_2_0_DECISIONS.md`, `docs/d012-preview/S6_PROCEDURE.md`;
check `git status` / `git log -3` on `feature/smartdoc-2.0`; continue with "Next action". Don't redo finished work.
Tracker: `backend/venv/Scripts/python.exe tools/smartdoc2/build_tracker.py`, then
`<scratchpad>/winvenv2/Scripts/python.exe tools/tracker/excel_recalc.py docs/SMARTDOC_2_0_MASTER_TRACKER.xlsx`.

## Checkpoint 2026-10-15 (end of session)

| | |
| --- | --- |
| Branch | `feature/smartdoc-2.0`. Remote tip `3489a6a` = the S7 deployment. Local commits after it: diagnostics (`Isolation refusals say why, safely...`) + this checkpoint -- see `git log origin/feature/smartdoc-2.0..HEAD` |
| D-012 | **S1-S6 done, S7 switched and technically verified, NOT yet VERIFIED** (waits for the owner's user test). S8, S9 not approved |
| 2.0 Preview | `dpl_3262fjM25cveZESWDNfkoBZF6csr` READY, https://smartdoc-git-feature-smartdoc-20-drajeto.vercel.app -- on Supabase project `smartdoc-preview` (`ksmwhnnupkrtzrupcitc`) and bucket `smartdoc-preview-files` |
| Proof of S7 | health (owner): `ok / preview / pinned yes / d8b55a9be8 / verified`. Independent (new project's logs): 10:38:17 Supavisor `Connection authenticated`; marker read once by `postgres` (pg_stat_statements); Storage `GET 200 /s3/smartdoc-preview-files/_smartdoc/identity.json` by `Boto3/1.43.101`. Before the fix: 9 x `password authentication failed` (wrong password in the branch DATABASE_URL; the guard refused correctly) |
| Production | unchanged: only read. No connections or storage access after 10:12:17 (before the S7 push); 2 users / 11 documents / 4 files, newest from 2026-10-13 |
| CI | `isolation-postgres.yml` green on 3489a6a (run 38718605753: isolation 75, PostgreSQL 14). Temporary branch `ci-only-d012-pin` (no Vercel deployment, `git.deploymentEnabled`) still on GitHub -- delete when D-012 is VERIFIED |
| Tests | backend 2806 passed / 16 skipped (PostgreSQL ones run in CI) on the diagnostics commit; isolation 89; Doctor 72 + 9; Vitest 560; Playwright 83 + 1 load-related flake that passes alone |
| Doctor v0 | prototype behind `?doctor=1` (S2-081 TESTING); measured 15/23 planted defects, 0 wrong proposals; gaps S2-083 |

## Rules carried over (owner)
No merge to main, no promote/Production deployment, no Production change, no deletion or move of user data, no
further Vercel/Supabase credential changes, no removal of Vercel Authentication, no paid services. S8 and S9 need
separate approval. Never create accounts or sign in on a deployed site (the owner runs the user test). Never print
secrets; Vercel env read = names/targets/branch/type only (`scratchpad/s6_check.py`, `vproj.py env`). Every push to
`feature/smartdoc-2.0` is a Preview deployment on the isolated project: push only verified, approved work.

## Next action
1. Owner's user test on the Preview (synthetic account `preview-check-<date>@example.com`, DOCX with a picture, edit,
   save, reload, DOCX/PDF export). Then, read-only: the account/document/files exist in `smartdoc-preview` and not in
   production (counts by that address and by time). Then mark D-012 VERIFIED (tracker S2-050, D-012, roadmap P8),
   delete the `ci-only-d012-pin` branch on GitHub.
2. Push the local diagnostics commit only with the owner's approval (it is a Preview redeploy; it is tested).
3. Then Document Doctor + SafeEdit (S2-083 gaps, B-022), keeping the editor and the roadmap.
