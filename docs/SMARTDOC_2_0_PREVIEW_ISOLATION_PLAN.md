# SmartDoc 2.0 Preview -- isolation plan (D-012, option a)

Status: **plan for the owner's approval** (2026-10-14). Nothing below has been switched. Production (project
`smartdoc`, branch `main`, https://smartdoc-peach.vercel.app) is not touched by any step: no Production variable,
deployment, database row or storage object changes.

## 1. Today (checked read-only, 2026-10-14)

| Thing | Production | Every Preview (incl. `feature/smartdoc-2.0`) |
| --- | --- | --- |
| Database | Supabase project `smartdoc-formatter` (`edmmjmsynjziahwtjuke`, eu-central-1) | **the same** (`DATABASE_URL` for target `preview`, no branch scope) |
| Storage | bucket `smartdoc-files` in the same project | **the same** bucket (`S3_*` for `preview`) |
| Other variables | CORS_ORIGINS, FRONTEND_URL, DATABASE_POOLER, JOB_BACKEND: production only | NEXT_PUBLIC_API_BASE_URL, PORT: both |
| Migrations | manual release step (`alembic upgrade head`); the app never migrates on start | -- |
| Supabase organisation | free plan; one project | -- |

So a 2.0 Preview reads and writes production data today (D-004). Accounts testers made on Previews are in the
production database.

## 2. Target

The `feature/smartdoc-2.0` Previews use **their own Supabase project** -- database, Storage bucket, keys -- and
nothing of production. Other Preview branches (e.g. 1.x hardening candidates) keep today's behaviour unless the
owner decides otherwise later.

## 3. Steps (each needs the owner's go-ahead where marked)

1. **New Supabase project** `smartdoc-2-preview`, eu-central-1 (same region as production and Vercel fra1).
   Cost checked with the Supabase API: **$0/month** on the free plan. Free projects pause after about a week
   without traffic (restore is one click; no data lost). *Owner approval: creating the project.*
   - Database branching was considered and rejected: ~$0.0134/hour (~$10/month) and it shares the organisation's
     production project.
2. **Schema, created safely**: `alembic upgrade head --sql` from this repository produces the exact SQL of the
   14 migrations production has (`initial_schema` ... `subscriptions_stripe_synced_at`, incl. RLS on every table);
   it is applied to the **new** project only, then `scripts/verify_database.py`-style check that the new
   database's Alembic head equals the code's. No production connection is opened.
3. **Storage**: a private bucket `smartdoc-preview-files` in the new project, with its own S3 access key pair
   (Supabase dashboard → Storage → S3 access keys). Production's bucket and keys are not reused.
4. **Preview credentials**, entered **by the owner** in Vercel (secrets never pass through Claude, the chat,
   logs or the repository), as **Preview variables scoped to the git branch `feature/smartdoc-2.0`**, which
   override the general Preview values for that branch only:
   `DATABASE_URL` (new project's transaction pooler), `DATABASE_POOLER=transaction`, `JOB_BACKEND` (same as
   production's value), `STORAGE_BACKEND=s3`, `S3_BUCKET=smartdoc-preview-files`, `S3_ENDPOINT_URL` (new project),
   `S3_REGION=eu-central-1`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, and the new guard variables
   `SMARTDOC_ENVIRONMENT=preview-2.0`, `PRODUCTION_DB_REF=edmmjmsynjziahwtjuke` (not secret).
   Claude checks the result with the Vercel API: names, targets and branch only, never values.
5. **Write guard (code, prepared now, inactive until step 4)**: when `SMARTDOC_ENVIRONMENT` says it is a
   preview, the backend **refuses to start** if `DATABASE_URL` or `S3_ENDPOINT_URL` contains `PRODUCTION_DB_REF`.
   A misconfigured Preview then fails its health check instead of writing to production.
   `/api/health` reports the environment name and a short hash of the database host (not the host itself),
   so the owner can see in the browser which database a deployment uses.
6. **Synthetic data only**: the new database starts empty. Testers sign up with test addresses; nothing is
   copied from production (no dump, no restore, no sync). An optional seed (a few sample projects in BG/EN)
   can be created by a script against the **Preview API** with a test account -- run by the owner, since Claude
   doesn't create accounts on deployed sites.
7. **Redeploy** the latest `feature/smartdoc-2.0` commit (a push), then verify (section 4).

## 4. Proof that the Preview can't write to production

- Vercel API: the branch-scoped variables exist for `feature/smartdoc-2.0` (names/targets/branch).
- `/api/health` on the Preview (owner, behind Vercel Authentication): `environment: preview-2.0`, database hash
  equal to the new project's (Claude computes the expected hash from the project ref).
- Supabase logs (read-only, MCP): after the redeploy, the **new** project's pooler shows the Preview's
  connections; the **production** project shows none from the Preview's deployment (checked over a test session
  by the owner: sign up, upload a DOCX with a picture, export).
- Storage: the uploaded picture is in `smartdoc-preview-files`; no new object in `smartdoc-files` in that window.
- The guard (step 5) is covered by backend tests: start refused with a production URL in preview mode.

## 5. Rollback

Remove the branch-scoped Preview variables for `feature/smartdoc-2.0` in Vercel and redeploy: the branch is back
on the general Preview values (today's state). The new Supabase project stays (paused or deleted later by the
owner); production was never changed, so nothing there needs undoing. Data created in the Preview database is
test data and can be dropped with the project.

## 6. Dependencies between Preview and production, and what stays shared

| Dependency | After the switch |
| --- | --- |
| Database, Storage, their keys | separate |
| Vercel project, domain family, Vercel Authentication | shared (same project; Previews keep Vercel Authentication) |
| Variables for both targets (NEXT_PUBLIC_API_BASE_URL, PORT) | shared; contain no production data access |
| Production-only variables (CORS_ORIGINS, FRONTEND_URL, ...) | not used by Previews |
| Email | disabled in both (EMAIL_BACKEND default) -- no mail to real people |
| Stripe | not configured in either |
| AI provider | not configured in either (D-007) |
| Users/sessions | separate databases → separate accounts; a production account doesn't exist in the Preview |
| Existing data testers created on earlier 2.0 Previews | stays in the production database, untouched (no migration, no deletion); listed for the owner to decide later |
| Other Preview branches | unchanged (still general Preview values) unless decided |

## 7. Remaining risks

- The free Supabase project pauses when idle; the first request after a pause fails until it's resumed.
- Schema drift: every future migration must be applied to both databases; the release checklist gets a line,
  and `verify_database.py` is run against both.
- Free-plan limits (500 MB database, 1 GB storage) apply to the Preview project separately.
- Canvas (`kind: "canvas"`) documents may be saved only after this switch is verified (D-012); until then they
  stay on local servers and in tests.
