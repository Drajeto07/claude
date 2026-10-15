# D-012 Preview infrastructure -- state (2026-10-15)

Nothing here is a secret: project ids, bucket names and instance ids identify resources, they open nothing.
Passwords and keys are set by the owner in Supabase and kept in the owner's password manager.

| | |
| --- | --- |
| Preview Supabase project | `smartdoc-preview`, id `ksmwhnnupkrtzrupcitc`, eu-central-1 (Frankfurt), free plan, $0/month (checked with Supabase's cost API before creating) |
| Production project | `smartdoc-formatter` -- **not changed**; only read (schema version and table names, bucket settings, "has no marker") |
| Schema (S4) | the repository's 14 migrations, applied to the new, empty project only: head `d41f7a60c9e2`, 16 tables, row-level security on all 16 -- identical names and version to production (no drift) |
| Database marker (S5) | `smartdoc_identity.deployment`: one row, `preview` / `d3c04003-bb8b-47c3-9ec1-2f2b92290187`; access revoked from public, anon, authenticated |
| Bucket (S3) | `smartdoc-preview-files`, private, no access policies, empty |
| Bucket marker (S5) | `identity.json` in this folder (`preview` / `76dfab40-9f23-4c1a-aaa9-26034ebea49b`) -- **to be uploaded by the owner** to `_smartdoc/identity.json` in the bucket |
| Prerequisite | isolation tests on a throwaway PostgreSQL in GitHub Actions: https://github.com/Drajeto07/claude/actions/runs/38701081333 (49 + 14 passed) |

The values for S6 (later, only with the owner's approval): `EXPECTED_DB_INSTANCE=d3c04003-bb8b-47c3-9ec1-2f2b92290187`,
`EXPECTED_STORAGE_INSTANCE=76dfab40-9f23-4c1a-aaa9-26034ebea49b`, `S3_BUCKET=smartdoc-preview-files`.

## Not done (owner's decision 2026-10-15)

- S6: no Vercel environment variable changed.
- S7: no switching redeploy.
- S8: Free Design documents are not saved in the shared database.
- S9: old test accounts in production are not touched.

Until S6, every Preview keeps today's configuration; the new project is not used by any deployment.

## The owner's three steps (about 10 minutes, no programming)

Open https://supabase.com/dashboard and choose the project **smartdoc-preview** (not *smartdoc-formatter*, which is
production -- check the name at the top left before every step).

1. **Database password (S2).** *Project Settings* -> *Database* -> *Reset database password* -> *Generate a password*
   -> copy it into your password manager -> *Reset password*. Don't send it to anyone (nor to Claude).
2. **Storage key (S3).** *Project Settings* -> *Storage* -> section *S3 Connection* -> *New access key* -> name it
   `smartdoc-preview` -> *Create* -> copy both values (Access key ID and Secret access key) into your password
   manager. The secret is shown only once.
3. **Bucket marker (S5).** Left menu *Storage* -> bucket **smartdoc-preview-files** -> *Create folder* -> name
   `_smartdoc` -> open the folder -> *Upload files* -> choose `identity.json` (sent with the report; also in this
   folder of the repository). Check: the folder shows one file, `identity.json`.

That's all for now. The values from steps 1 and 2 are used only in S6 (Vercel), which waits for a new decision.
