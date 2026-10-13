# First public release on Vercel (RELEASE, 2026-10)

The first release runs as **one Vercel project** with two [services](https://vercel.com/docs/services)
(`vercel.json` at the repository root), on the owner's Hobby plan:

| Service | What | Built from |
| --- | --- | --- |
| `frontend` | the Next.js app, at every path but `/api/*` | `frontend/` (Next.js, built by Vercel) |
| `backend` | the FastAPI API, at `/api/*` (`/api/v1/...`, `/api/health`, `/api/ready`) | `backend/Dockerfile.vercel` (a container function: the backend image's packages and fonts) |

Both are served from **one origin** (`https://<project>.vercel.app`), so the session cookie is the site's own:
a split frontend and API on two `*.vercel.app` hosts would make it a third-party cookie, which browsers
don't send. The frontend's server reaches the API over a service binding (`API_INTERNAL_URL`, injected by
Vercel); the browser calls `/api/v1/...` on the page's own origin (`NEXT_PUBLIC_API_BASE_URL=/`).

Backing services: PostgreSQL is the Supabase project `smartdoc-formatter` (eu-central-1), reached through
its **transaction pooler** (Supavisor, port 6543: the direct host is IPv6-only and serverless instances
must not each hold a pool); files are in **Supabase Storage** through its S3 interface (bucket
`smartdoc-files`, private).

## Settings

Set in the Vercel project's Environment Variables (Production, and Preview where noted). Secrets are
entered by the owner in the Vercel dashboard and never pass through chat, logs or this repository; the
others can be set by anyone.

| Name | Value | Secret |
| --- | --- | --- |
| `DATABASE_URL` | Supabase → Connect → Transaction pooler URI, as `postgresql+asyncpg://...:6543/postgres` (`ssl=require` is added by the app) | yes |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Supabase → Storage → S3 Connection → new access key | yes |
| `ANTHROPIC_API_KEY` | optional: without it AI steps take their non-AI fallbacks | yes |
| `ADMIN_TOKEN`, `METRICS_TOKEN` | optional: long random strings, for `/api/v1/admin/operations` and `/api/metrics` | yes |
| `NEXT_PUBLIC_API_BASE_URL` | `/` (the API on the app's own origin) | no |
| `PORT` | `8000` (the container's port) | no |
| `STORAGE_BACKEND`, `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION` | `s3`, `smartdoc-files`, `https://edmmjmsynjziahwtjuke.storage.supabase.co/storage/v1/s3`, `eu-central-1` -- **required**: without them files are kept inside the container and lost when it stops | no |
| `SENTRY_DSN` | the client key of Sentry project `drajeto/smartdoc-backend` (Settings → Client Keys) | no (public key) |
| `CORS_ORIGINS`, `FRONTEND_URL` | the production URL (`https://<project>.vercel.app`); a deployment's own Vercel URLs are allowed too (`VERCEL_URL` ...). Needed for e-mail links and Stripe's return addresses | no |
| `EMAIL_BACKEND`, `SMTP_*`, `EMAIL_FROM` | only once a sending domain is verified (Resend: `smtp`, `smtp.resend.com`, port 465, `SMTP_SECURITY=ssl`, user `resend`, the API key as `SMTP_PASSWORD` -- a secret) | password: yes |

The image itself (`backend/Dockerfile.vercel`) defaults what Vercel always needs, so a missing setting can't
break it: `JOB_BACKEND=eager` (a job runs inside its request: no worker, no Redis), `DATABASE_POOLER=transaction`,
`EMAIL_BACKEND=disabled` (the app says it sends no e-mail rather than claiming a link went out),
`MAX_UPLOAD_SIZE_MB=4` and `MAX_REQUEST_SIZE_MB=5` (under Vercel's own 4.5 MB body limit, so the app's message is
what a person sees), `LOG_FORMAT=json`, `LOG_REQUESTS=true`. A project setting of the same name wins.

The schema is migrated before a release, never by the API at start: `alembic upgrade head` against the
database (or, as so far, each revision applied through the Supabase connector).

## Limits of this release

- **Uploads and downloads of 4.5 MB or more fail** (Vercel's function body limit): the app refuses uploads
  over 4 MB with its own message; an export over 4.5 MB can't be downloaded.
- A request -- and so a job, which runs inside its request -- has **300 s** at most (Hobby).
- No job worker: the hourly sweep (expired export files, account clean-up) doesn't run; stuck-job
  recovery doesn't either. Both are a scheduled call away (post-launch).
- Rate limits are counted per instance (no Redis): an abuser spread over instances gets more.
- No e-mail leaves the app (no sending domain; `EMAIL_BACKEND=disabled`): sign-up works without confirming the
  address, and the app says plainly that a password reset isn't available yet rather than promising a link.
  So the site stays behind Vercel Authentication until e-mail works (tracker REL-023).
- Billing is off (Stripe is a sandbox account only); every workspace is on the free plan.
- Vercel Hobby is for non-commercial use: move to Pro before charging anyone.

## Releasing and rolling back

1. Push to the release branch: Vercel builds a preview of both services. Smoke-test it.
2. Promote to production (or merge to the production branch). The production URL is the project's.
3. Roll back: Vercel → Deployments → the previous production deployment → **Instant Rollback** (the
   database needs nothing: migrations are additive first; this release added none).
