# D-012 S6/S7 -- connecting the 2.0 Preview to its own project (for the owner's approval)

Status: **S6 approved (owner enters the 12 variables), S7 not approved** (2026-10-15). No Vercel variable has been
changed by Claude; no redeploy has been made.

## The rule from the moment the variables exist

Adding variables in Vercel does **not** start a deployment by itself; a deployment uses the variables as they are
when it is built. So once the 12 branch variables exist, **any push to `feature/smartdoc-2.0` is the switch** (S7).
Claude pushes nothing to that branch between the owner's S6 and the owner's S7 approval.

## Are the 12 enough? (architecture checked, 2026-10-15)

- Backend (Vercel container from `backend/Dockerfile.vercel`): reads only its settings. Of those that open something,
  the project holds just the database (`DATABASE_URL`) and the store (`S3_*`, `STORAGE_BACKEND`); no Stripe, SMTP,
  Anthropic, Redis, Sentry, admin or metrics secrets exist in the project. The image itself sets
  `DATABASE_POOLER=transaction` and `JOB_BACKEND=eager` (no separate worker on Vercel).
- Frontend (Next.js): reads `API_INTERNAL_URL` (Vercel's link to the same deployment's backend), the public API path
  and build flags -- no database or store credentials.
- General Preview values today (every branch): `DATABASE_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`,
  `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `STORAGE_BACKEND` -- each gets a branch value among the 12, so nothing
  of production's is inherited by the branch. (`DATABASE_POOLER` is kept in the 12 for clarity; the image sets it.)

## The pin (code, ready, pushed only as S7)

The backend treats a Vercel Preview of `feature/smartdoc-2.0` -- by Vercel's own `VERCEL_ENV` and
`VERCEL_GIT_COMMIT_REF`, which this project exposes at runtime -- as a preview that must prove its isolation even if
`SMARTDOC_ENVIRONMENT` is missing; so does any deployment carrying any guard setting (`PRODUCTION_DB_REF`,
`EXPECTED_*`). Proof is always the real markers read from the connected database and bucket. `/api/health` shows
`"pinned": "yes"` when the pin sees the branch. Pushing it before S6 would stop today's Preview (it would refuse to
start on production's values) -- so it is committed locally and pushed as the S7 deployment itself.

## Checks done before S6 (read-only)

| Step | Check | Result |
| --- | --- | --- |
| S1 | project `smartdoc-preview` (`ksmwhnnupkrtzrupcitc`), eu-central-1, ACTIVE_HEALTHY; organisation on the free plan | OK |
| S2 | database password reset by the owner | owner-confirmed; proven at S7 (the Preview can't connect otherwise) |
| S3 | bucket `smartdoc-preview-files` private, 0 access policies, 1 object; S3 key pair made by the owner | OK; the keys aren't visible in the database (as it should be) -- proven at S7 |
| S4 | head `d41f7a60c9e2`, 16 tables, RLS on all 16, 0 users, 0 documents | OK |
| S5 database | `smartdoc_identity.deployment`: exactly one row, `preview` / `d3c04003-bb8b-47c3-9ec1-2f2b92290187`; owner `postgres` (the app's login) can read it; `anon`/`authenticated` can't | OK |
| S5 bucket | `_smartdoc/identity.json`, 82 bytes, `application/json`; its ETag equals the one computed from the file in this folder (byte-identical); the app's parser reads `preview` / `76dfab40-9f23-4c1a-aaa9-26034ebea49b` | OK |

## The variables (target **Preview**, Git branch **feature/smartdoc-2.0** only)

Vercel uses a branch-specific Preview value instead of the general Preview value of the same name, for that branch
only. Every other branch keeps the general values; Production is not touched.

| Name | Value | Kind |
| --- | --- | --- |
| `DATABASE_URL` | Supabase -> smartdoc-preview -> *Connect* -> *Transaction pooler* URI, with the database password | secret (owner) |
| `S3_ACCESS_KEY_ID` | the key made in S3 | secret (owner) |
| `S3_SECRET_ACCESS_KEY` | the key made in S3 | secret (owner) |
| `DATABASE_POOLER` | `transaction` | plain |
| `STORAGE_BACKEND` | `s3` | plain |
| `S3_BUCKET` | `smartdoc-preview-files` | plain |
| `S3_ENDPOINT_URL` | `https://ksmwhnnupkrtzrupcitc.storage.supabase.co/storage/v1/s3` (compare with Storage -> S3 Connection -> Endpoint) | plain |
| `S3_REGION` | `eu-central-1` | plain |
| `SMARTDOC_ENVIRONMENT` | `preview` | plain (switches the guard on) |
| `PRODUCTION_DB_REF` | the production project's id: Supabase -> **smartdoc-formatter** -> *Project Settings* -> *General* -> *Project ID* (also given in the report) | plain, not secret |
| `EXPECTED_DB_INSTANCE` | `d3c04003-bb8b-47c3-9ec1-2f2b92290187` | plain, not secret |
| `EXPECTED_STORAGE_INSTANCE` | `76dfab40-9f23-4c1a-aaa9-26034ebea49b` | plain, not secret |

12 rows, all new, all branch-specific. No existing row is edited or deleted.

## Falling back to production credentials: what can happen and what stops it

A name that has **no** branch-specific value falls back to the general Preview value -- today production's. So:

| Forgotten branch value | What the Preview then gets | What stops it |
| --- | --- | --- |
| `DATABASE_URL` | production's pooler URL | start refused: the URL's user names the production project (layer 1) |
| `S3_ENDPOINT_URL` | production's endpoint | start refused: it names the production project (layer 1) |
| `S3_BUCKET` | `smartdoc-files` at the new endpoint | requests refused: no such bucket, no marker (layer 2) |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | production's keys at the new endpoint | requests refused: they don't open the new store, no marker (layer 2) |
| `STORAGE_BACKEND` | `s3` (the same as the general value) | no effect |
| `PRODUCTION_DB_REF`, `EXPECTED_*` | nothing | start refused (layer 1) |
| **`SMARTDOC_ENVIRONMENT`** | nothing: the guard stays off | **not stopped by the app**: with the other values right it uses the new project unguarded; with them wrong too, it is back on production |

The gap is `SMARTDOC_ENVIRONMENT` itself. Two protections are proposed:

1. **Before any redeploy** Claude lists the variables (names, targets, branch -- never values) and checks that all
   12 exist for Preview + `feature/smartdoc-2.0` and that the Production rows are exactly as before. Missing one:
   stop, no redeploy.
2. **Pin in code** (approved, ready; see above): a Vercel Preview of `feature/smartdoc-2.0` must prove isolation
   even if `SMARTDOC_ENVIRONMENT` is missing. It closes the gap in the last row of the table.

Other Preview branches keep production's general Preview values (the owner's choice: branch-specific only). The
plan's default policy -- no production credential for any Preview -- remains recommended as a later step.

## Proof after S7 (owner + Claude)

1. Claude: the deployment for the branch is READY.
2. Owner: open `<preview address>/api/health` (signed in to Vercel). Expected: `"environment": "preview"`,
   `"pinned": "yes"`, `"isolation": "verified"`, `"database": "47821310ce"` (pooler host `aws-0-...`) or `"d8b55a9be8"` (`aws-1-...`).
   Production's would be `a59def7216`.
3. Owner: on the Preview, create `preview-check-2026-10-<day>@example.com`, upload a .docx with a picture, export it.
4. Claude, read-only: the Preview project has that account, the document and new files in its bucket; the
   production project has **no** user with that address and no files created after the redeploy (only counts by
   that address and by time -- nobody's data is read).
5. Optional live test of the guard: set `EXPECTED_DB_INSTANCE` (branch) to `00000000-0000-0000-0000-000000000000`,
   redeploy -> health says `refused: database: the marker names another instance` and the app serves nothing ->
   put the right value back, redeploy -> `verified`.

## If something is wrong

- Health says `refused: ...` or `pending`: the Preview serves nothing and writes nothing -- a safe stop. Tell Claude
  the reason shown (it names no secret); correct that one branch value; redeploy.
- The page shows errors and health is `verified`: an app problem on the new project, not a data risk; logs by Claude.
- Never: copy production values into the branch rows, delete `SMARTDOC_ENVIRONMENT` / `PRODUCTION_DB_REF` /
  `EXPECTED_*`, or "go back" by deleting the branch rows so the branch falls back to the general (production) values.
  To pause the 2.0 Preview, set the branch `DATABASE_URL` to `disabled`: it then refuses to start (checked).
