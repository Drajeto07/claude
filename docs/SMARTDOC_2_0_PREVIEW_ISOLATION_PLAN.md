# SmartDoc 2.0 Preview -- isolation plan (D-012, option a), revision 2

Status (2026-10-15, owner's decisions): **S1-S5 done, S6-S9 not done**. The separate Preview project exists with
the schema and its identity markers (details: `docs/d012-preview/README.md`); the bucket marker file waits for the
owner's upload. **Nothing has been switched**: no Vercel variable changed, no switching redeploy, no Free Design
documents in the shared database, old test accounts in production untouched. Production was only read. The guard is
inactive until a Preview names itself (`SMARTDOC_ENVIRONMENT`), which happens only with S6. The isolation tests ran
on a throwaway PostgreSQL in GitHub Actions (`.github/workflows/isolation-postgres.yml`, no secrets): 49 + 14 passed.

Revision 2 (2026-10-14) was the plan for the owner's approval: the decision -- a separate database and Storage for
Previews -- confirmed, nothing switched.

What changed from revision 1, at the owner's request:

1. Rollback never returns a Preview to Production's database or Storage (section 6).
2. The guard is fail-closed and checks the **identity of what the Preview is connected to**, not URL text
   (section 4); the pooler and the direct endpoint are both covered.
3. Migrations on a completely empty database are proven, and future migrations / drift have a procedure
   (section 5).
4. The risk that *other* Preview branches use Production today is documented, with a default policy: no
   Preview of any branch holds a Production credential (section 3).
5. No secret goes anywhere it could be read back (section 7).
6. A click-by-click procedure for the owner, with how to prove Production can't be written from a Preview
   (section 8). Section 9 lists the exact actions awaiting permission.

## 1. Today (checked read-only, 2026-10-14)

| Thing | Production | Every Preview, every branch |
| --- | --- | --- |
| Database | the production Supabase project (eu-central-1) | **the same database** (`DATABASE_URL` has one value for target *Preview*, no branch scope) |
| Storage | the production bucket in the same project | **the same bucket** (`S3_*` for *Preview*) |
| Other variables | CORS_ORIGINS, FRONTEND_URL, DATABASE_POOLER, JOB_BACKEND: Production only | NEXT_PUBLIC_API_BASE_URL, PORT: both |
| Migrations | manual release step (`alembic upgrade head`); the app never migrates on start | -- |
| Supabase organisation | free plan; one project | -- |

So today **every** Preview deployment -- of `feature/smartdoc-2.0` and of any other branch pushed to the
repository -- runs with Production's database and Storage keys and can read and write real users' data.
Vercel Authentication keeps strangers out of the Preview URLs, but not the code: whatever a branch contains runs
with Production's write access. Accounts testers made on 2.0 Previews are in the production database.

## 2. Target

All Previews -- not only `feature/smartdoc-2.0` -- use **one separate Supabase project** (database, private
Storage bucket, its own keys) and hold **no Production credential**. Production keeps its own variables on
target *Production* only. A Preview that is not connected to its own project serves nothing.

## 3. Default policy for every Preview branch (point 4)

- **No Production write credential is ever stored for target *Preview***, for any branch. The Preview values of
  `DATABASE_URL` and `S3_*` are *replaced* by the preview project's (not overridden for one branch), so a branch
  without its own variables -- an old 1.x branch, a dependency-update branch, a new experiment -- lands on the
  preview project, never on Production.
- Every Preview names itself (`SMARTDOC_ENVIRONMENT=preview`) and so must prove its isolation (section 4).
- Production-only variables stay on target *Production* only. A variable shared by both targets may hold
  nothing that reaches data (today: the API base path and the port).
- Vercel's protection of fork pull requests stays on (a fork's code never gets the project's variables
  without approval), and Vercel Authentication stays on for Previews.
- Risk accepted: all Preview branches share **one** preview database. Test data from one branch is visible to
  another; that is test data only.

## 4. The guard: fail-closed, by identity (point 2)

Two layers, both in the backend (`app/config.py`, `app/isolation.py`), covered by `tests/test_preview_isolation.py`
(49 tests; the PostgreSQL ones run in the isolated workflow `.github/workflows/isolation-postgres.yml` on every push to the 2.0 branch -- passed before S4 and S5).

**Layer 1 -- the Preview's own settings** (refuses to start):
- a Preview must name `PRODUCTION_DB_REF` (the production project's id -- not a secret) and the two instance
  ids it expects; if any is missing it does not start (missing is a refusal, never a pass);
- it does not start when the database URL's host, port, user or database name mentions production -- this
  covers Supabase's **pooler**, where every project of a region has the same host and only the user name
  (`postgres.<project id>`) differs, and the **direct** endpoint (`db.<project id>.supabase.co`), in any letter
  case; nor when the Storage endpoint or bucket name mentions it.

**Layer 2 -- what the connected resources say they are** (refuses every request):
- the preview database holds one row in its own schema `smartdoc_identity` (`environment = preview`, a random
  instance id); the preview bucket holds `_smartdoc/identity.json` with the same two fields, and its own id;
- before serving anything -- and before the start-up's own housekeeping writes (marking interrupted jobs,
  sweeps) and before a job worker runs -- the Preview reads both markers back **from the database and the bucket
  it is actually connected to** and compares them with the ids it expects;
- Production has no such marker, so a Preview pointed at Production by any route -- a pasted URL, the pooler,
  a different endpoint, a rollback, a typo -- finds none and refuses. So does a second row, another
  environment, another id, a marker that can't be read, a database or bucket that doesn't answer;
- refused: every request gets **503** except `/api/health`, which says `isolation: refused: <reason>` (the reason
  names no host, user or key); it is tried again every 30 s. Proven: it stays proven for the life of the process;
- `/api/health` also shows a short fingerprint of the database (host, port, user, database together -- so two
  projects on the same pooler differ), never the address itself.

Nothing in the guard writes. The markers are written once by `scripts/preview_identity.py create`, which itself
refuses a database that already holds accounts or documents (Production does; a new project doesn't), refuses
one that already has a marker, and refuses settings that mention production -- all before writing anything.
`scripts/preview_identity.py check` is the read-only version of the guard.

Not covered, by design: the guard can't stop someone with Production's credentials from using them outside the
app; the policy in section 3 is what keeps them out of Previews.

## 5. Schema: empty database, future migrations, drift (point 3)

**Empty database.** Proven on every push to the 2.0 branch by `.github/workflows/isolation-postgres.yml` (and on pull requests by CI's *Migrations on PostgreSQL* job): each takes an **empty
PostgreSQL 17**, runs `alembic upgrade head`, `alembic check` (the models and the migrated schema match),
`alembic downgrade base` and `alembic upgrade head` again, then the PostgreSQL-only tests. Locally,
`alembic upgrade head --sql` produces the same 14 migrations offline (head `d41f7a60c9e2`, Production's head),
including row-level security on every table.

**On the new project** (step S4 in section 9): the SQL is applied to the new project only, through the
Supabase connection Claude already has (no password passes through anyone), then checked read-only:
`alembic_version` = the code's head; the list of tables = the models'; Supabase's security advisor reports RLS
on every table; no other schema touched.

**Every future migration** (release checklist, one line added):
1. CI green (the empty-database job above).
2. Apply to the **preview project first**; run the app's Preview against it.
3. Apply to Production as today (manual release step, owner's approval).
4. Drift check, read-only, on both: `SELECT version_num FROM alembic_version` equals `alembic heads` of the
   commit being released. A difference stops the release.

**Drift check at any time:** the same query on both projects; also `/api/ready` on the Preview answers only
when its database answers. A Preview whose database is behind fails its own tests rather than writing wrong data.

## 6. Rollback that never returns to Production (point 1)

There is no step anywhere that puts Production values into target *Preview*. The rollback paths:

- **Something is wrong after the switch** (health says `refused`, or tests fail): leave it refused. A refused
  Preview serves nothing and writes nothing -- this *is* the safe stop. Fix forward (correct the value, upload the
  missing marker), or
- **return to the previous isolated configuration**: the previous preview values are kept by the owner in the
  password manager (never in the repository or chat); re-entering them and redeploying restores the last
  working isolated setup;
- **give up on Previews for a while**: delete the Preview values of `DATABASE_URL` / `S3_*` and keep
  `SMARTDOC_ENVIRONMENT=preview`. Without a database the Preview refuses to start -- again a stop, not a fallback.

Explicitly not a rollback: "copy the Production values back to Preview", "remove the Preview variables so the
branch falls back to the shared ones" (after the switch there are no shared data variables), or turning the
guard off. Production itself is never changed by the switch, so nothing there needs undoing.

## 7. Secrets (point 5)

- Database passwords, connection strings, S3 keys and API keys are typed by the owner directly into Supabase
  and Vercel, and kept in the owner's password manager. They never appear in GitHub, the tracker, docs, logs,
  screenshots or the chat; Claude never asks for them.
- Claude reads Vercel variables by **name, target and branch only** (never values), and uses the Supabase
  connection it already has for schema work, which shows no password.
- The app's health and refusal messages name no host, user or key; the setup script prints only the two
  instance ids (random, not secrets). The production project id is not a secret (it is in every public URL of
  the project), but it is kept out of this document anyway.
- The secret scan runs before every push.

## 8. The owner's procedure, click by click (point 6)

Time: about 30 minutes. Steps marked *(Claude)* are done by Claude after the approval in section 9; the
owner's steps are the ones that involve a password or key.

**A. The new Supabase project** *(Claude creates it, if approved; or the owner: supabase.com → New project)*
1. Name `smartdoc-preview`, region **Central EU (Frankfurt)**, plan Free ($0).
2. Owner: the project asks for a database password -- generate it, save it in the password manager, don't send
   it to anyone.

**B. Schema** *(Claude)* -- applies the migrations to the new project only and checks them (section 5).
The owner sees in Supabase → *Table Editor* the same table names as in Production, all empty.

**C. Identity markers**
1. *(Claude)* writes the database marker in the new project and gives the owner a small file
   `identity.json` (two lines: `preview` and a random id -- nothing secret).
2. Owner: new project → *Storage* → *New bucket* → name `smartdoc-preview-files`, **Public: off** → Create.
3. Owner: open the bucket → *Create folder* `_smartdoc` → open it → *Upload* → `identity.json`.
4. Owner: *Storage* → *S3 Connection* (Settings) → *New access key* → save both values in the password manager.

**D. Vercel variables** (vercel.com → project `smartdoc` → *Settings* → *Environment Variables*)
For each name below: find the row whose target is **Preview** → *Edit* → paste the new value → *Save*.
Never edit a row whose target is **Production**.

| Name (target Preview) | New value |
| --- | --- |
| `DATABASE_URL` | new project → *Connect* → *Transaction pooler* URI (with the new password) |
| `S3_ENDPOINT_URL` | new project → Storage → S3 Connection → *Endpoint* |
| `S3_BUCKET` | `smartdoc-preview-files` |
| `S3_REGION` | `eu-central-1` |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | the key from C4 |
| `STORAGE_BACKEND` | `s3` |
| `SMARTDOC_ENVIRONMENT` *(new, Preview only)* | `preview` |
| `PRODUCTION_DB_REF` *(new, Preview only)* | the production project's id (Supabase → Production project → *Settings* → *General* → Project ID) |
| `EXPECTED_DB_INSTANCE`, `EXPECTED_STORAGE_INSTANCE` *(new, Preview only)* | the two ids Claude gives in C1 (not secrets) |

Then: *Deployments* → the latest `feature/smartdoc-2.0` deployment → *⋯* → *Redeploy*.
*(Claude)* checks, by name/target only, that every row above exists for Preview and that no new row was added
for Production.

**E. Verify** (owner, signed in to Vercel, in the browser)
1. Open `<Preview address>/api/health`. It must say `"environment": "preview"` and `"isolation": "verified"`,
   and the `database` fingerprint must equal the one Claude computes for the new project.
   Anything else (`refused: …`, `pending`) → stop here and tell Claude; the Preview is serving nothing.
2. Open the Preview, create an account `preview-check-<date>@example.com`, create a document titled
   `ISOLATION CHECK <date>`, upload a .docx with a picture, export it.

**F. Prove Production is not writable from the Preview**
1. Production project → *Table Editor* → `users` → filter `email` = the address from E2 → **no rows**.
   Preview project → same → **one row**.
2. Production project → *Storage* → production bucket → sort by date → **no new file** since step D.
   Preview bucket → the picture from E2 is there.
3. Vercel → *Environment Variables* → filter target **Preview** → open each data variable's value → it contains
   the **new** project's id, never the production one. (Only the owner looks at values.)
4. Optional live test of the guard, with no risk to Production: change `EXPECTED_DB_INSTANCE` (Preview) to
   `00000000-0000-0000-0000-000000000000`, redeploy → `/api/health` says `refused: database: the marker names
   another instance`, and the app shows errors instead of data. Put the right id back, redeploy → `verified`.
5. Automated: the backend tests prove a Preview pointed at Production -- pooler, direct endpoint, any case --
   refuses, before and after start (section 4).

## 9. Exact actions awaiting the owner's permission

Each is a separate yes/no. None touches Production's database, Storage, variables or deployments.

| # | Action | Who | Cost | Reversible |
| --- | --- | --- | --- | --- |
| S1 | Create Supabase project `smartdoc-preview` (free plan, Frankfurt) | Claude via Supabase, or the owner | $0/month | delete the project |
| S2 | Owner sets and stores its database password | owner | -- | -- |
| S3 | Create private bucket `smartdoc-preview-files` and an S3 key pair in the **new** project | owner | $0 | delete bucket/key |
| S4 | Apply the 14 migrations to the **new** project and check them (section 5) | Claude | -- | drop the project |
| S5 | Write the database identity marker in the **new** project; owner uploads `identity.json` | Claude + owner | -- | drop the schema / file |
| S6 | Replace the **Preview**-target values of `DATABASE_URL`, `S3_*`, `STORAGE_BACKEND`; add `SMARTDOC_ENVIRONMENT`, `PRODUCTION_DB_REF`, `EXPECTED_*` for Preview | owner | -- | section 6 (never back to Production) |
| S7 | Redeploy the latest `feature/smartdoc-2.0` Preview and run section 8 E–F | owner + Claude | -- | -- |
| S8 | Allow Free Design (canvas) documents to be saved on the Preview once S7 says `verified` | owner's decision | -- | -- |
| S9 | Later, separately: what to do with test accounts earlier 2.0 Previews left in the production database (keep / list / remove) | owner's decision | -- | -- |

Until S1–S7 are approved and done: Previews keep today's (shared) configuration, the guard stays inactive
(no `SMARTDOC_ENVIRONMENT`), and no Free Design document is saved outside local servers and tests.

## 10. Dependencies after the switch

| Dependency | After the switch |
| --- | --- |
| Database, Storage, their keys | separate; Previews hold no Production credential |
| Vercel project, Vercel Authentication | shared; Previews keep Vercel Authentication |
| Variables for both targets (NEXT_PUBLIC_API_BASE_URL, PORT) | shared; reach no data |
| Production-only variables (CORS_ORIGINS, FRONTEND_URL, ...) | unchanged, Production only |
| Email, Stripe, AI provider | not configured in either (no mail to real people, no charges, D-007) |
| Users/sessions | separate databases → separate accounts |
| Other Preview branches | on the preview project too (section 3) |

## 11. Remaining risks

- The free preview project pauses after about a week without traffic; until it's resumed (one click), the
  Preview's health says `refused: database ...` -- a stop, not a fallback.
- Free-plan limits (500 MB database, 1 GB storage) apply to the preview project separately.
- Two databases to migrate: the checklist in section 5 is a manual step; a forgotten preview migration shows as
  a failing Preview, not as a Production problem.
- The guard covers the app and its worker. A person holding Production's credentials can still use them
  elsewhere; keeping them out of Preview (section 3) and in the password manager is what prevents that.
