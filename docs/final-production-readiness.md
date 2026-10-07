# Final production readiness

The production-hardening programme's final report (brief §112, tracker DOCS-010), as of **2026-10-07**, branch
`feature/smartdoc-production-hardening` (commits up to `88f66f3` and the one carrying this file). It builds on the
SaaS transformation's audit ([`architecture/final-audit.md`](architecture/final-audit.md), 2026-09-26), which describes
the platform the hardening started from. Per task, with evidence and commits: `SmartDoc_Master_Implementation_Tracker.xlsx`;
how each part works: [`docs/`](README.md).

**Verdict: not ready to launch yet, and ready to be made so.** The product's code is complete for its P0 and P1
scope and verified by the suites below. What stands between it and production is not code but decisions and
operations only the owner can make: the hosting target, the Stripe account and prices, an e-mail provider, a real
Anthropic key and a round of real documents through every AI path, an OCR engine if scanned PDFs matter, and the
first start of the Docker stack on a machine that can run Docker (section 15).

## 1. What changed

The hardening ran in 18 phases (brief §104). In short:

- **Editor integrity and content preservation** (Phase 1): nested blocks in cells, list items and quotes survive the
  editor and both exports; content the editor can't hold stops the save instead of vanishing; the Document Fidelity
  Report on every import and export, with a word-by-word content check and the policy for each feature (§90); a
  machine-readable capability matrix (`GET /api/v1/capabilities`, 96 features).
- **AI fidelity** (Phase 2): every AI answer that touches text is checked token by token against its source;
  content-changing instructions become proposals; per-job AI budgets; prompts that fence the document as data.
- **Word fidelity** (Phase 3, 29 tasks): the original Word file kept and unchanged blocks copied back byte for byte;
  hidden text, character and paragraph formatting, sections with their own page setup and headers, list levels and
  labels, table geometry, pictures, fields, comment threads, tracked changes, content controls, notes, heading
  numbering, drawings kept; 37 Word-authored fixtures with their expected losses, checked through the whole path and
  in Word itself (the Word gate).
- **Security and resource limits** (Phase 4): malformed Word and PDF files refused cleanly; picture, ZIP, XML and PDF
  limits; one link policy and one field policy; external targets stripped; SVG refused; one error envelope; a
  security regression suite (`pytest -m security`).
- **Performance** (Phase 5): delta autosave, a linear table export, bounded compressed history, UTF-8 JSON storage,
  benchmarks, job safety (timeouts, retries, dead letters).
- **Accounts, billing and entitlements** (Phase 6): e-mail sending, password reset, e-mail verification, password
  change, account deletion, session management, a sign-in delay; usage units, plans as data, atomic plan limits
  (AI operations reserved per call), Stripe flows.
- **PDF** (Phases 7-8): a geometry read and page classifier for every PDF; a deterministic PDF-to-editable
  reconstruction (reading order, headings, lists, tables, pictures, captions, running headers) with a confidence per
  block and per aspect; editable or layout-focused import; an OCR interface.
- **Translation** (Phase 10): block and selection translation as proposals with their formatting, translated
  versions as new documents, glossary, language detection, metering.
- **Multilingual rendering** (Phase 11): a font catalogue and a deterministic FontResolver; HarfBuzz shaping and the
  Unicode bidi algorithm for Arabic, Hebrew, Devanagari and Thai in PDFs; per-script fonts in Word.
- **Format by Example** (Phase 12): a reference's tables, lists and heading numbering are part of its look; the AI's
  heading mapping is checked against the sizes; the look is tried on the document (before/after) before it is kept.
- **Document Health 2.0** (Phase 13): nine more checks and deterministic fixes as reviewable proposals.
- **Review Changes** (Phase 14): one review panel for every proposed change, by category; content changes need
  explicit acceptance, enforced on the server.
- **Accessibility and observability** (Phase 16): an accessibility checker for documents; an app with no serious axe
  violations; request, operation and job ids on every log line; Prometheus metrics.
- **Final testing** (Phase 17): performance gates against the base branch (which caught and fixed a real regression);
  the end-to-end workflows; the documentation tree.

## 2. What was preserved

- **The AI never formats and never rewrites.** It returns structured, validated data; only the deterministic engine
  makes styles. Every new AI use keeps the rule: Format by Example's AI only maps headings (and is checked), Document
  Health's AI may only explain (HLTH-003, not built), translations are proposals.
- **No silent content loss.** Everything an import or export can't keep is reported, item by item (the fidelity
  report and `unsupportedFeatures`); the content check verifies every word.
- **The priority model, conflict handling, templates, the two independent exporters** and every earlier test.
- **Everything a user could do before**, and the old `/api/...` paths as deprecated aliases.

## 3. What was rebuilt

- **The save protocol** (PERF-003): a save sends what changed (`PATCH /content`), the server rebuilds the whole from
  its own copy.
- **The Word export** writes into the original file (DOCX-011, DOCX-028): unchanged blocks keep their XML.
- **The PDF export's text layer**: fonts per script run, shaped and bidi-ordered text (`export/rtl.py`, `app/bidi.py`).
- **The PDF import**: from text only to a geometry-based reconstruction (P2E-001..007).
- **The proposal system**: one change model (REV-001) for instructions, translations and health fixes, with
  server-side acceptance (REV-003).
- **Version history**: compressed, bounded (50 steps, 10 MB a document).

## 4. Remaining limitations

- **Not run for real:** the Anthropic model (every AI path ran against test doubles; no key was configured), Stripe
  (code tested against a stand-in; no account), SMTP (outbox only), Redis and the arq worker, S3 storage, the Docker
  images and the compose stack (this machine can't run Docker), PostgreSQL concurrency beyond CI's job.
- **The Word gate** (every Word fixture opened in Word itself) last ran on 2026-10-06, before Phases 11-17 changed
  the exports (per-script fonts, structure from Format by Example). Run it again before release (GATE-006).
- **The editor paginates by whole blocks** (a block taller than a page runs past the margin); the exports paginate
  for real.
- **Open P2/P3 tasks** (by the tracker): batch formatting, export and translation (Phase 15); AI explanations of
  health issues (HLTH-003); repair and clean copy (REV-004/005); FONT-005; operations data (OBS-003); a browser
  matrix (TEST-043); the PDF layout-preserving architecture (Phase 9); and Phase 3's follow-ups.

## 5. Supported document features

"Supported" means implemented and proved by a test. The capability matrix (`backend/app/capabilities.py`,
`GET /api/v1/capabilities`) lists all 96 features with their import, edit, export and round-trip support, policy and
tests; in sum: 34 kept as they are and editable, 19 kept for export but not editable, 32 kept with a stated
approximation. Highlights:

- **Word, kept and editable:** paragraphs and headings (with Word's own styles), character formatting (underline
  styles, caps, spacing, raised text, language), paragraph formatting (indents, spacing, borders, tab stops,
  direction), lists with every level's label and numbering, checklists, tables with merged cells, shading, borders and
  widths, pictures with alt text, captions, quotes, code, page and section breaks with each section's page setup,
  headers and footers (first-page and even-page too) with page numbers, footnotes and endnotes, hyperlinks, hidden
  text (kept hidden), heading numbering.
- **Word, kept for export:** equations, fields, bookmarks, comment threads, content controls, tracked changes,
  drawings, text boxes (as their paragraphs), the original's styles and properties.
- **PDF in:** text PDFs rebuilt into paragraphs, headings, lists, tables, pictures and captions with their confidence;
  layout-focused mode.
- **Out:** Word (written into the original when there is one) and PDF (embedded fonts, every script an installed font
  draws, right-to-left text), both checked after writing.
- **Text in:** Markdown, plain text through the AI (checked) or the segmenter.

## 6. Unsupported document features

From the matrix (9 unsupported, 2 blocked) and the reports:

- **Unsupported, reported:** linked and VML pictures, pictures over the limits, symbol-font characters other than
  checkboxes, Markdown pictures from web addresses, control characters, a PDF's form fields, annotations and outline
  as such, scanned pages in a PDF with text (they come in as pictures).
- **Blocked, with a message:** a scans-only PDF while no OCR engine is configured; editor content the model can't
  hold (the save stops).
- **Approximated, reported:** character scale and text effects, drop caps, text boxes as paragraphs, fields that
  fetch from outside (kept as their last result), styles outside the app's range.
- **Not offered:** other formats (.doc is refused with a message; .odt, .rtf, HTML not accepted), editing equations
  or comments, generating a table of contents, real-time co-editing (deliberately), a tagged (accessible) PDF.

## 7. PDF conversion limitations

- No OCR without an engine (`OCR_PROVIDER=none` is the only one; the engine is the owner's choice): a scans-only PDF is
  refused, scanned pages in a text PDF come in as pictures.
- The reconstruction is used only when the layout read had every page and found at least 95% of the text read's
  words; otherwise the document is the plain text, and says why.
- Tables need ruling lines (a grid of at most 500 x 40); a table laid out with spaces alone stays paragraphs
  (`pdf.unruled_tables`). Upright pages only for tables.
- Pictures within caps (25 megapixels each, 150 in all, 300 pictures, 30 s).
- Nothing is placed at its exact position (frames and anchors are the layout-preserving architecture's, Phase 9, not
  built); layout-focused mode keeps pages, fonts and sizes, not positions.
- Headings are found by size and weight, lists by markers that count on: guesses are marked (confidence 0.55) for review.
- 1,000 pages at most.

## 8. Translation limitations

- Needs the Anthropic key (`TRANSLATION_PROVIDER=ai`); `pseudo` is for tests and demos. Not yet run against the real
  model.
- Every answer is checked (tags, digit groups, percentages, units by measure, identifiers, locked glossary terms,
  length): a segment that fails stays in the original language, said so. The check can't judge the translation's
  meaning or style: translations are labelled "AI-assisted translation — review required" and always wait as proposals.
- Language detection covers 22 languages by script, letters and common words; unsure, it says so, and the target is
  never guessed.
- Metered by characters (`maxTranslationCharacters`, a placeholder limit). Batch translation of many documents is
  not built (FEAT-003).

## 9. AI limitations

- One provider (Anthropic) behind `AIProvider`; never run against the real model in this programme.
- The AI reads at most about 160,000 characters for structure analysis (the rest is split without it, and the
  document says so), 400 listed elements for instructions, 300 for style analysis.
- Every call has a budget per job and request (calls and seconds), a timeout and retries; past the budget or the
  plan's AI operations the deterministic fallback runs.
- Prompt injection: documents are fenced in per-call tags as data; answers are schema-bounded and checked; content
  changes can only become proposals, and only the user's acceptance applies them (REV-003, enforced in
  `apply_operations`).
- The AI never scores (Document Health, accessibility) and never explains yet (HLTH-003).

## 10. Security posture

- **Accounts:** argon2 hashes; server-side sessions in HTTP-only cookies, expiring, revocable, listed per browser;
  password reset and e-mail verification with single-use hashed tokens; a sign-in delay and new-browser e-mail;
  account deletion with its data.
- **Isolation:** every endpoint authenticates, authorizes and fetches within the user's workspace; the security suite
  (`pytest -m security`) sweeps every route; RLS on every Supabase table (the public Data API gets nothing).
- **Input:** uploads judged by their bytes; Word, ZIP, XML, picture and PDF limits (one table, SEC-013); malformed
  files refused with a clear error; one link policy (no `javascript:`), one field policy, external targets removed,
  SVG refused.
- **Transport and browser:** strict headers, a nonce-based CSP for the app and `default-src 'none'` for the API,
  restricted CORS, HSTS when served over HTTPS only.
- **Abuse:** rate limits (sign-in, registration, AI, uploads, exports, overall; shared through Redis in production);
  atomic plan limits.
- **Secrets:** `SecretStr` settings; a secret scan before every push; the repository is public and holds none.
- **Logs:** audit lines for every account, document, billing and refusal event; request, operation and job ids; never
  a document's content.
- **Known open item:** `style-src-attr 'unsafe-inline'` remains for the editor's inline styles (SEC-020 notes;
  owner's decision whether to accept).

## 11. Performance results

Measured with `backend/scripts/benchmark.py` (PERF-002); the baseline numbers are in
[`performance/`](performance/README.md).

- Word export of a 500 x 8 table: **247 s → 0.7 s** (PERF-001); of 6,801 blocks: **15.3 → 5.1 s** (PERF-008).
- A one-paragraph save of a 300-page document: **2.2 MB → 1.4 KB** each way (PERF-003); at 12,201 elements, under
  1 KB instead of 9.3 MB.
- Saving at 12,201 elements: 1.47 → 1.32 s, the event loop's longest stall **586 → 214-239 ms** (PERF-008).
- Version history compressed and bounded (PERF-004); document JSON stored as UTF-8 (PERF-006).
- **The performance gate** (TEST-041) holds every change to its base branch on the same machine (CI does this on
  every pull request). Its first run found the PDF export of 500 blocks 66% slower after Phase 11's FontResolver;
  fixed (per-character script cache, a one-run fast path): **0.640 → 0.377 s** against the base's 0.385 s
  ([`performance/gate-2026-10-07.md`](performance/gate-2026-10-07.md)).
- Not measured: load (many users at once), PostgreSQL under load.

## 12. Billing/usage model

- **Usage units** (`app/billing/units.py`): documents created, processing jobs, exports, AI operations, PDF pages,
  OCR pages, translation characters, batch jobs, plus documents, templates and storage held.
- **Plans as data** (`app/billing/plans.json`): Free, Pro, Business, each with its entitlements (export formats,
  documents, document size, exports, PDF and OCR pages, translation characters, batch jobs, AI operations,
  templates, storage, priority processing). **The numbers and prices are placeholders**: the owner's decision.
- **Enforced before the work**, atomically when requests race (402 `plan_limit`); AI operations and translation
  characters reserved per call and given back when it fails.
- **Stripe**: Checkout, the customer portal and a signed webhook with every subscription event handled in order
  ([`billing/README.md`](billing/README.md)); **off** until the owner's Stripe account, prices and webhook exist.

## 13. Test results

The last full runs, 2026-10-07:

| Suite | Result |
| --- | --- |
| Backend (pytest) | **2344 passed, 11 skipped** (commit `570a2da`; the skips need PostgreSQL -- run in CI --, a private Word document, or a font this machine lacks) |
| Security suite (`-m security`) | inside the above, every route |
| Frontend unit (Vitest) | **277 passed** (36 files) |
| End to end (Playwright, Chromium) | **49 passed** (incl. axe accessibility on every main page); one keyboard-timing flake in `kept-blocks` seen once, 6/6 on rerun |
| Mutation checks | every phase: Phase 11 11/11, Phase 12 9/9, Phase 13 12/12, Phase 14 8/8, accessibility 11/11, observability 11/11 |
| Performance gate | passed after the fix above |
| Word gate (in Word) | 60/60 on 2026-10-06; **to be rerun** after Phases 11-17 |
| CI | defined for every pull request (backend, migrations on PostgreSQL, frontend, audit, e2e, performance gate); results visible to the repository's owner |

No test touches the real database: each gets its own SQLite file.

## 14. Release gates

| Gate | Status | Evidence |
| --- | --- | --- |
| GATE-001 No silent content loss | evidence passes | TEST-022 true-fidelity round trip, EDIT-006, FID-002 content check, in today's run |
| GATE-002 No unauthorized document access | evidence passes | TEST-030 security suite, every route |
| GATE-003 AI cannot silently change content | evidence passes | AI-004 text check, AI-006 proposals, REV-003 server-side acceptance |
| GATE-004 Plan limits atomic | evidence passes | PLAN-003 race tests (SQLite); PostgreSQL in CI only |
| GATE-005 Safe file uploads | evidence passes | SEC-010..012 malformed and oversized files |
| GATE-006 DOCX valid | **to rerun** | the Word gate, last 2026-10-06 |
| GATE-007 PDF valid | evidence passes (in-suite) | every export read back and checked; no external validator run |
| GATE-008 Multilingual PDF readable | PASS (queued in the tracker) | FONT-006 script matrix |
| GATE-009 PDF conversion has confidence/reporting | PASS | P2E-005 |
| GATE-010 Translation preserves formatting | PASS | TRAN-010 |
| GATE-011 No destructive translation overwrite | PASS | TRAN-006 |
| GATE-012 Critical E2E passes | evidence passes | TEST-040, 49 Playwright tests |
| GATE-013 Migrations clean | CI only | `alembic check` and down/up on PostgreSQL in CI; locally the models match head |
| GATE-014 No high-severity security findings | to review | the dependency audit job's latest result and the open audit findings |
| GATE-015 Monitoring exists | evidence passes | OBS-001 metrics, OBS-002 ids in logs; dashboards and alerts not set up (no deployment) |

"Evidence passes" means the linked tests pass in today's runs; a gate is set to PASS in the tracker only from its
verification run (Phase 18's release audit).

## 15. Known risks

1. **The real AI model** may answer differently from the test doubles: structure analysis, instructions, Format by
   Example's mapping and translations all fall back or refuse safely, but their quality is unmeasured. Run real
   documents through every path with a real key before launch.
2. **First deployment:** the Docker images and the stack have never started end to end (INFRA-010, blocked here); the
   worker, Redis and S3 have run only against stand-ins.
3. **Word compatibility after Phases 11-17:** rerun the Word gate.
4. **Fonts in production:** without the Noto fonts, Arabic, Hebrew, Devanagari, Thai and CJK can't be drawn in PDFs
   (reported, not silent).
5. **Placeholder plan limits and prices**: launching with them would be a business risk, not a technical one.
6. **Supabase's free plan** pauses an idle project; production needs a paid plan and backups (the asset store has none).
7. **Flaky end-to-end test** (kept-blocks keyboard selection): harden if it recurs.

## 16. Recommended next features

In order of value, keeping to the product's promise -- a document plus an example, template or instructions gives a
consistent style with the content untouched (§93):

1. **Launch basics** (not features): hosting, Stripe on with real prices, SMTP, a real AI key and a real-document
   round, the Word gate, error tracking with alerts on the metrics (`docs/operations`).
2. **Review the AI's structure before formatting**: confirm or correct low-confidence headings, lists and captions
   (from imports and PDFs) in the Review panel.
3. **Official requirements as an input**: read an institution's formatting rules once into a template, showing what
   was understood.
4. **Repair and clean copy** (REV-004/005) on the review layer built here.
5. **Batch formatting** (FEAT-001): one look applied to many documents -- the Business plan's natural feature.
6. **A table of contents** built from the headings and exported as a real Word field.
7. **AI explanations of health and accessibility issues** (HLTH-003), never scores.
8. **A tagged PDF** for accessibility, now that the document side is checked.
9. **Teams**: invitations, roles, shared templates.
10. **A Bulgarian interface.**

Not next: Word-clone features (drawing, free page layout, real-time co-editing).
