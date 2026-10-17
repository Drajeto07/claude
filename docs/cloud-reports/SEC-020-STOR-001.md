# SEC-020 nonce CSP, STOR-001 storage retention

Branch `cloud/sec-020-stor-001`, from `feature/smartdoc-production-hardening` at 8966ec7. Commit prefix `cloud SEC-020:` / `cloud STOR-001:`.

## Summary

**SEC-020.** The Next.js app sends a Content-Security-Policy built per request with a fresh nonce:
`script-src 'self' 'nonce-...' 'strict-dynamic'`, no `'unsafe-inline'`, and `'unsafe-eval'` in development only. It is set in
`frontend/proxy.ts` (Next.js 16's name for middleware; the guide in `node_modules/next/dist/docs/01-app/02-guides/content-security-policy.md`).
Every other directive and header is kept. All 15 routes now render per request. The full Playwright suite passes.

**STOR-001.** A table of every stored file (pictures, kept originals, a job's upload, an export file, OCR later) with its retention,
how it is deleted, who reads it, its type and its limit is in `docs/security/README.md` ("Stored files"). The gaps found are closed,
each with a test; the kept original's retention is configurable (`KEPT_ORIGINAL_RETENTION_DAYS`, default 0 = as long as the document).

## What style-src still needs, and why

- `style-src 'self' 'nonce-...'` for `<style>` elements. Next.js stamps its own; **Tiptap injects one** (its editor CSS), so it is given the
  nonce with `injectNonce` (`frontend/lib/nonce.tsx`: the layout reads `x-nonce` and a context hands it to the two `useEditor` calls). Without it the editor
  loses its CSS (checked: the E2E violation test fails when `injectNonce` is removed).
- `style-src-attr 'unsafe-inline'` for style attributes. This is the one `'unsafe-inline'` left. A nonce can't go on an attribute. I measured instead
  of assuming: with `style-src-attr 'none'` the flows I drive (sign-up, templates, a Word file with tables, typing) report no violation, because React and
  ProseMirror set most styles through the CSSOM, which is not checked. But a probe page shows the browser **does** block `setAttribute("style")` and a
  `style=""` in HTML parsed with `innerHTML` into a *detached* element. That is how ProseMirror parses pasted HTML and writes `toDOM` attributes, so
  `'none'` would silently drop pasted colours, alignment and indents. I kept `'unsafe-inline'` there. A style attribute can't run script. Owner decision below.

## What became dynamic

Everything. The build (`next build`) lists all 15 routes as `ƒ (Dynamic)` (before: static). The root layout reads `headers()` (for the nonce), which opts the whole
tree into per-request rendering. Nothing is cached by Next.js any more and there is no CDN-cacheable HTML; the pages are small client shells that fetch data
in the browser, so the cost is the server rendering a shell per request. The proxy skips `/_next/static`, `/_next/image`, the favicon and prefetches.

## Files changed

- Frontend: `proxy.ts`, `lib/csp.ts` (policy + nonce), `lib/nonce.tsx`, `app/layout.tsx`, `next.config.ts` (CSP removed from `headers()`, the other four headers kept),
  `editor/DocumentEditorShell.tsx`, `components/documents/DocumentPreview.tsx` (`injectNonce`), tests `proxy.test.ts`, `e2e/csp.spec.ts`.
- Backend: `app/security/serving.py` (new: `file_response`), `app/api/assets.py`, `app/api/jobs.py`, `app/api/documents.py` (every file goes through it),
  `app/jobs/files.py`, `app/jobs/runner.py`, `app/services/job_service.py`, `app/services/asset_cleanup.py`, `app/config.py`, `.env.example`, test `tests/test_storage_retention.py` (23 tests).
- Docs: `docs/security/README.md` (Stored files table, the pages' CSP, Kept originals), `docs/architecture/jobs.md`.

## STOR-001: gaps found and closed

| Gap | Fix | Test |
|---|---|---|
| A job's upload whose delete failed when the job ended (runner logs and goes on) stayed: for a **dead letter** forever (retention never removes it), else up to 7 days | `sweep_job_files` deletes again the upload of any finished job (succeeded, failed, cancelled, dead letter) that still records one, and clears the key once it is gone; a pending or running job's is left alone | `test_the_upload_of_a_finished_job_is_deleted_again_if_it_was_left_behind` (5 cases incl. an old dead letter), `..._that_has_not_finished_is_left_alone` |
| An export that fails, times out or is cancelled **after writing its file** never recorded the key: the file (a user's document) stayed forever | the runner removes `jobs/{id}/output` when an export job ends any way but success; the retention sweep also looks for it where it is written | `test_an_export_that_fails_after_writing_its_file_leaves_none_behind`, `test_an_export_file_a_failed_job_wrote_but_never_recorded_goes_with_its_job_row` |
| An export past `JOB_FILE_TTL_HOURS` was still downloadable until the hourly sweep ran (up to an hour late) | `JobService.export_file` refuses it from the moment it expires | `test_an_export_past_its_time_cannot_be_downloaded_even_before_the_sweep_deletes_it`, `test_the_sweep_ends_an_export_with_the_time_lowered` |
| Files served by four routes each built their own response; the job file's type came from the job's JSON, the asset's from its row | one `file_response`: only a type the app stores is sent as itself, anything else as `application/octet-stream` + `attachment`; `nosniff`; `default-src 'none'; sandbox`; Content-Disposition (`inline` for a picture, `attachment` otherwise, RFC 6266 filename); exports `Cache-Control: private, no-store`. The kept original (served by `/assets/{id}`) used to have no disposition | `test_every_file_goes_out_...`, `test_a_picture_is_shown_in_place_...`, `test_a_type_the_app_never_stores_is_sent_as_opaque_bytes...` (5), `test_a_stored_picture_is_served_in_place_and_the_kept_original_as_a_download`, `test_an_export_file_is_a_private_download_of_its_own_type`, `test_an_export_whose_recorded_type_is_not_one_the_app_makes...` |
| The kept original had no retention setting | `KEPT_ORIGINAL_RETENTION_DAYS` (default 0, `ge=0`): the existing daily asset sweep also deletes a `.docx` asset older than that, counted from when it was stored, even while its document exists. The document stays; its Word export is written without the original and says `export.docx.source_missing` (existing behaviour). Only the original's type is selected, never a picture | `test_by_default_the_original_stays_as_long_as_its_document`, `test_with_a_time_set_an_older_original_goes_and_its_export_says_so`, `test_a_picture_is_never_taken_by_the_time_set_for_originals` |

Already right, kept (existing tests, not weakened): a pending job's cancel and a running job's cancel delete the upload
(`test_job_safety.py` 574, 658), a dead letter and a stuck dead letter delete it (388, 770), a success or failure through the runner
(`test_jobs.py`), an export of a deleted document expires at once, `JOB_FILE_TTL_HOURS` is at least 1 so an export can't be kept forever.

## Tests added and results

- `frontend/proxy.test.ts` (6): the production policy; eval only in development and never inline scripts; style-src/style-src-attr; the other directives kept; a new nonce per call and none of unsafe-inline/eval in script-src; the request carries the policy and nonce on to the render.
- `frontend/e2e/csp.spec.ts` (2): over HTTP, the header, `strict-dynamic`, no unsafe-inline/eval in script-src, no unsafe-inline in style-src, `connect-src` has the API, `frame-ancestors 'none'`, `nosniff`/`X-Frame-Options` still sent, a different nonce on two responses, **every `<script>` tag of the page carries the nonce**; in a browser (violation listener + console), the templates page, a Word file with tables in the editor and typing report no violation.
- `backend/tests/test_storage_retention.py` (23).
- Results: backend full suite **1931 passed, 4 skipped** (the skips are the PostgreSQL-only tests (no PostgreSQL URL set) and the real-Word-file test); Vitest **247 passed** (31 files); `npx tsc --noEmit` clean after `next typegen`; `npm run lint` 0 errors (one warning in the git-excluded local Playwright config); `next build` ok; **Playwright through the lock: 35 passed, 1 skipped (visual, as on the base)**. A first full run had one failure (`templates.spec.ts`, a soft navigation not completing within 20 s) while the backend suite was running on the same machine; the spec passes alone and the whole suite passed again on a quiet machine. Watch it in CI.

## Commands run

`npm ci`; `npx next typegen && npx tsc --noEmit`; `npm run lint`; `npx vitest run`; `NEXT_DIST_DIR=.next-w6 npx next build`; `flock /tmp/e2e.lock npx playwright test --config playwright.local.config.ts [csp.spec.ts | templates.spec.ts]` and the whole suite twice; `/tmp/venv/bin/python -m pytest -q -p no:cacheprovider tests/test_storage_retention.py` and the whole backend suite.

## Mutation results (each killed by the named tests)

- Frontend: `injectNonce` removed from both editors: `csp.spec.ts` browser test fails (violations). `'unsafe-inline'` added to script-src: 3 `proxy.test.ts` tests fail. A constant nonce: the fresh-nonce test fails. (A probe with `style-src-attr 'none'` showed the browser blocks `setAttribute("style")` and detached `innerHTML` style attributes: the reason for keeping it.)
- Backend, 10 mutations, all killed: nosniff dropped from `file_response`; the type allow-list removed; the sandbox CSP removed; the strict export TTL removed; the leftover-upload backstop removed; the guessed output key removed; the failed-export discard removed; the kept-original retention off; the retention also taking pictures (type filter removed); the kept original served inline.

## Migrations

None.

## Risks and open questions

- All pages render per request now (above); if CDN-cached HTML is ever wanted, the alternative is the experimental SRI mode in the same guide, which keeps static pages with hash-based script policy. Not tried: it is experimental.
- `style-src-attr 'unsafe-inline'` stays (above).
- `NEXT_PUBLIC_API_BASE_URL` is read in `proxy.ts` and is inlined at build time like before (the Dockerfile text stays true). Not run against a Docker build/standalone server here; CI's e2e uses `next start`.
- The proxy does not run for `/_next/static` and prefetches: static files carry no CSP, as the guide says.
- Clearing `ProcessingJob.input_key` in the sweep: nothing reads the key after a job has finished (checked in code and tests), and the runner itself still leaves it set.
- A key never recorded is found only for export files (known path). A crash between storing a picture/upload and committing its row leaves a blob nobody can list (providers have no listing). A pending job whose queue message was lost keeps its upload until retention removes the row (7 days). Both documented.
- An export file has no size cap of its own (bounded by the document); I did not add one.
- Deleted originals are not recorded on the document: an export says "no longer stored" each time; the stored import report still says the original was kept.

## Decisions for the owner

1. `KEPT_ORIGINAL_RETENTION_DAYS`: default 0 keeps originals as long as the document. Pick a number to delete sooner (the Word export then loses styles, headers and footers kept from the original, and says so).
2. Accept `style-src-attr 'unsafe-inline'` (no script can run from it), or accept losing pasted formatting under `'none'`.
3. Whether the editor should tell the person when the original was removed (today only the export report does).

## Not done

OCR output storage (not built; its row is reserved in the table). Account deletion removing a user's files (ACCT, no such feature yet). Size cap for exports.
