# Security notes

These are the security decisions the code relies on, with pointers to where each is enforced. The full list of open
and done items is in the tracker's SECURITY rows.

## Values that reach styles

Formatting rule values are checked per property before they can reach CSS, Word or PDF (SEC-022,
`docs/formatting/README.md`). Before this, `center;background-image:url(…)` sent as an alignment through the style
endpoint or an instruction ended up in every viewer's editor. The Mark model validates a run's font name and
colours for the same reason.

## Damaged Word files

- **Always a 400.** A Word file that can't be read gets 400 `invalid_file` with a message written for people (SEC-010).
  That holds for every route and job that reads one: upload, the import job, reference-style extraction. It is never
  a 500, and nothing is stored.
- **Every XML part is checked first** (`parsers/docx.py::_check_parts`). This runs before python-docx opens the file,
  streamed, with no tree built. Each part must be well-formed XML and have no DTD; the Open Packaging Conventions
  forbid DTDs. Two gaps this closes:
  - parts nothing here reads (the theme, the font table) would go back out broken in a Word export into the original;
  - python-docx reads a DTD's entities as nothing, so the text around them was lost without a word.
- **A failure after that** says the file couldn't be read. That covers no body, a root that isn't WordprocessingML,
  or a limit of the reader. The log names the exception's type and where it was raised, never its message, which can
  quote the file.
- **The corpus.** `backend/tests/malformed_docx.py` builds its variants from two fixtures. The tests pin which are
  read (with every word) and which are refused, with which message.

## Damaged PDFs

- **What can't be read is a 400.** A PDF that can't be read gets 400 `invalid_file` with its message (SEC-011): not
  valid, password-protected, too much data, no text, or damaged. This covers the upload, the import job and an
  instructions file. Whatever pypdf throws becomes a refusal; the log names the exception's type and where it was
  raised.
- **What was read in spite of damage says so.** pypdf mends a damaged file where it can. A stream that doesn't
  decode, or an object that isn't there, loses text without an exception. `parsers/pdf.py::read_pdf` collects pypdf's
  warnings for each read (a ContextVar, so concurrent imports don't mix) and tells the repairs that lose nothing (a
  wrong xref offset, a `/Prev` loop) from the ones that lose text.
  - An import then reports `pdf.damaged`, a content change, so "No content changes" is never claimed.
  - An instructions file, which has no report, is refused.
  - A damaged file with no text left says it is damaged, not "scanned".
- **pypdf's warnings never reach the log.** Its messages can quote the file. The log gets how many repairs a file
  needed and of what kind.
- **Pictures that can't be counted** are said to be possibly left out, never counted as none.

## Pictures

- **The limits** (SEC-012, `security/files.py`):
  - one picture: 20 MB, 50 megapixels, 20,000 pixels on a side;
  - one document: 1000 pictures and 200 MB of them. An export holds a document's pictures in memory at once.
- **Judged by the header.** A picture's file can claim any size in a few bytes, and decoding one takes width x
  height x 4 bytes. `picture_problem` reads only the header, before anything decodes the picture.
- **Only PNG, JPEG, GIF, WebP and BMP are ever opened** (`formats=` on every `Image.open`). Otherwise Pillow would try
  43 formats, EPS among them, which runs Ghostscript. A picture must also be the type it claims: stored, it is
  served under that type.
- **Pillow's own backstop** covers any decode that doesn't ask first, reportlab's included.
  - `MAX_IMAGE_PIXELS` is half the limit, so Pillow refuses to open anything past the limit itself, whatever
    warning filters are in force.
  - A warnings filter set at import doesn't survive an import inside `catch_warnings()` (pytest's collection is
    one), so no guarantee rests on one.
- **Where each is enforced:**
  - Word import: a picture past the limits is left out and said to be (`docx.image.too_large`, `docx.image.too_many`).
  - The editor's save: such a picture is removed and named. A save that would take the document past its number
    or bytes is refused with 413 `too_large` before anything is stored. The editor then says why and doesn't
    retry.
  - Export: one stored before the limits is left out (`export.image.too_large`).
- **Autosave backs off.** The autosave's own writes into the editor (ids, the looks saved) no longer schedule a
  save. Before, a failing save was sent again every 1.2 seconds instead of backing off, because each try gave an
  unsaved block a new id.

## SVG

SVG can carry script, so it is never taken in as a picture (SEC-017, `tests/test_svg.py`):
- **Pasted:** an SVG data URI, or SVG bytes that claim to be a PNG, is removed on save, and nothing is stored.
- **From Word:** a picture with Word's own PNG fallback beside it (svgBlip) is read as the PNG. An SVG-only one is
  reported as an unsupported format.
- **From Markdown:** markdown-it takes no `data:` address but a web picture's, so such a line stays the text it is.
- **Never opened:** `picture_problem` refuses it, and Pillow can't open SVG.
- **Never drawn:** an SVG handed to an export is left out, and said to be.
- **Served safely:** a stored asset is served with its stored type, `nosniff` and `Content-Security-Policy:
  default-src 'none'; sandbox`, both by the asset route and by the API's own headers. Removing both layers fails
  the test.

## Text no document can hold

Control codes XML can't hold never reach a document (SEC-023, `docs/document-model`). Before this, one backspace
from a PDF's broken font made the document's Word export fail for good.

## AI

- **Prompt injection (AI-009, SEC-018).** A document is fenced as data in every AI call, and every answer field is
  bounded before it can reach a document or the screen (`docs/ai/README.md`).
- **Destructive changes need a person.** An AI instruction can't delete, insert or move text itself; it can only
  propose it (AI-006).
- **Bounded spend.** Each job and request has a call and time allowance, so one document can't spend the AI budget
  for hours (AI-008).

## Links

One policy decides which addresses a link may have (SEC-014, `security/links.py::safe_href`).
- **The rule.** A Word file or a PDF opens its links outside the app, so a link is an absolute address of a kind
  that opens a page, a mail, a call or a chat: http, https, ftp, ftps, mailto, tel, callto, sms, xmpp. A bare
  `www.` address gets https://. It is never javascript:, data:, vbscript: or file:, a UNC path, or a relative
  address (Word resolves one against the folder the file sits in). Nor is it longer than 2048 characters.
- **Read as browsers read it.** Control codes are dropped and tabs and newlines inside are removed before the scheme
  is read, so `java\tscript:` and a leading `\x01` don't get through.
- **Whoever sends it, the model keeps no other address** (`Mark.href`). A link with any other address keeps its text
  and loses the link.
  - Word import: reported as `docx.link.unsafe`.
  - Markdown: markdown-it itself refuses javascript:, vbscript:, file: and data:, and a relative or other-scheme
    link is reported as `markdown.link.unsafe`.
  - The editor: named in the status bar. The editor's Link extension uses the same rule (`editor/linkPolicy.ts`,
    as `isAllowedUri`), so pasted links it can't keep stay text from the start.
- **Neither export writes another address as a live link**, whatever it is handed. The health check never calls
  one usable.
- **The two stay the same.** `frontend/tests/fixtures/link-policy.json` holds the cases both implementations must
  answer alike: obfuscated javascript:, data:, vbscript:, file:, UNC, protocol-relative, relative, #anchor.
  `backend/tests/test_link_policy.py` and `frontend/editor/linkPolicy.test.ts` both read it. One known
  difference: the editor's check doesn't parse the host, so an address with an IPv6 bracket left open shows as
  a link there until the document is opened again.

## Word fields

A field is code Word runs when it updates the document, and some reach outside it (SEC-015,
`security/fields.py`):
- DDE and DDEAUTO start a program.
- INCLUDETEXT, INCLUDEPICTURE, INCLUDE, IMPORT, LINK, RD and DATABASE pull in outside content, and tell its server
  the file was opened.
- MACROBUTTON runs a macro; PRINT sends raw printer codes.
- AUTOTEXT, AUTOTEXTLIST and GLOSSARY insert a building block from a template -- the attached one, or that of
  whoever opens the file -- so what they show comes from outside the document.

So only the fields that show what the document itself holds or works out stay fields (`ALLOWED_FIELDS`): numbers
and pages, dates, properties, cross-references, tables of contents and indexes, citations, form fields, formulas
and mail-merge fields, plus HYPERLINK to an address a link may have (SEC-014) or to a bookmark. Any other field
keeps its last result, as text:
- **In the Word file kept as the original.** An upload is cleaned before it is read or kept
  (`security/package.py::clean_package`, `neutralize_fields`): the body, headers, footers, notes, comments and building blocks. Nested fields and ones
  deleted with tracked changes are cleaned too, since rejecting the deletion would bring one back. So no export
  written into the original carries one out, from any part, and copied unchanged blocks are clean.
- **In the document.** The import reports it as `docx.field.unsafe`; the importer keeps no such field whoever calls
  it.
- **In what an export writes back.** A kept field fragment is written only when its field may be one. A field running
  across paragraphs whose start is refused loses its end too, so Word never sees an end without a start.
- **From the browser.** A save keeps the server's `preservedAttributes` for each block, at any depth
  (`provenance.py::keep_preserved`, like `keep_provenance`). A new block has none, so no client can add a
  field, or any other fragment, to the next Word export.

## What a Word file points to outside itself

The Word file kept as the original is what every Word export is written into, so it keeps no external target but
links a link may have (SEC-016, `security/package.py`). Word follows some external targets on its own when it opens
a file, and each of these goes at upload, with what referred to it:
- a remote template (`attachedTemplate`, a known way in for macros);
- a linked picture (a tracking pixel): the picture itself stays when it is also embedded, only its link goes;
- a sub-document or linked object;
- a mail-merge data source, with its connection string and query (Word runs the query when it opens the file).

A link to an address a link may not have (SEC-014) keeps its text; the link goes. The import reports both:
`docx.link.unsafe` in the importer's own words, and `docx.external.unsafe`. Nothing is left referring to a
relationship that is gone (the package check agrees), and Word opens the cleaned file and its export without repair.

## Kept originals

- **Retention.** An uploaded Word file is kept as it was, for Word exports (DOCX-010). It belongs to its workspace,
  is served only to members, and is checked by its SHA-256 before use.
- **Deletion.** It goes a day after its document is deleted (the unused-asset sweep).
- **What travels.** A Word export written into it carries the file's own properties, including custom properties and
  a sensitivity label. That is the owner's own metadata, kept on purpose. A PDF carries neither.
- **Which original XML is copied.** Unchanged blocks are copied from the original body (DOCX-028). Where each block
  came from (`Element.sourceBlocks`) and its fingerprint (`Element.sourceHash`) are the server's: `PUT /content`
  keeps the stored values for each element id and ignores what the client sends. A client can't make the export
  copy XML in place of text it changed, or write one original block for two elements. How many elements each
  original block was read into (`Document.sourceBlockUse`, DOCX-028B) is set at import, and no save changes it.
  So a block deleted in the editor is never copied back.
- **Links in copied blocks.** A block whose original XML has a link the app doesn't allow (a `javascript:` or
  `file:` target, as a relationship or a HYPERLINK field) is never copied: it is written anew, with the plain text
  the importer made of the link.

## Pictures from addresses

The Markdown importer doesn't fetch pictures from the addresses in pasted text. A server-side fetch of any address
is a risk of its own (SSRF), so they are reported as left out instead (`markdown.image`).

## Word metadata

- Custom document properties and sensitivity labels are reported by the import, never with their values.
- Excel and Word on the development machine stamp `MSIP_Label_*` properties (with the organisation's tenant id) into
  Office files on save:
  - the tracker tools strip them;
  - the pre-push secret scan flags them (except the synthetic all-zero label id used in tests);
  - Word fixtures are scrubbed before they are committed.
- `корекции.docx` in the public history carries one (SEC-021, needs a decision from Boril).

## Limits

What costs time or memory is bounded, so no request or upload ties a worker up for minutes (SEC-013, PERF-007).
Each limit has a test, run on an ordinary small file with the limit lowered for the test (`tests/test_limits.py`
and the tests named per area).

| What | Limit | Where | Past it |
|---|---|---|---|
| A request's body | 25 MB (`MAX_REQUEST_SIZE_MB`) | `security/http.py::RequestSizeLimit` | 413 `too_large` |
| An uploaded file | the plan's `maxDocumentSizeMb` (`billing/plans.json`), at most 10 MB (`MAX_UPLOAD_SIZE_MB`) | `api/uploads.py::read_limited`, `EntitlementsService` | 413 / 402 |
| A Word package | 1,000 parts; an XML part 50 MB; 200 MB unpacked; past 1 MB, no part compressed more than 100:1 | `security/files.py::check_docx` | 400 `invalid_file` |
| A Word file's XML | well-formed, no DTD; libxml2's own caps (256 levels deep, 10 MB of text in one node: `huge_tree` off) | `parsers/docx.py::_check_parts`, `security/files.py::parse_xml_part` | 400 `invalid_file` |
| A Word file's length | 50,000 paragraphs and 50,000 table cells, headers, notes and comments counted (about 18 s at worst) | `parsers/docx.py` (`MAX_PARAGRAPHS`, `MAX_TABLE_CELLS`) | 400 `invalid_file` |
| A PDF | 1,000 pages; a stream decompressed to 75 MB (pypdf's own); 2 MB of content on one page (about 13 s at worst); 60 s of reading in all, checked between pages | `parsers/pdf.py` | 400 `invalid_file` |
| Pictures | 20 MB, 50 megapixels, 20,000 pixels a side; 1,000 and 200 MB in a document | `security/files.py` (SEC-012) | left out, or 413 `too_large` |
| Pasted text | 2,000,000 characters (deepest Markdown nesting in it reads in under a second) | `schemas/document.py`, `schemas/jobs.py` | 422 |
| Nesting | blocks 8 deep: a table in a cell, a list in a quote | `models/document.py::MAX_BLOCK_DEPTH` | 422 |
| A link's address | 2,048 characters | `security/links.py::MAX_HREF` | text, no link |
| Direct styles in one save | 10,000 | `schemas/document.py` | 422 |
| The AI | 50 calls and 900 s per job (`AI_CALLS_PER_JOB`, `AI_SECONDS_PER_JOB`); 20 pieces per structure analysis | `ai/budget.py`, `ai/structure_analysis.py` | the rest split by rules, and said to be |
| Requests | all 600/min a session; sign-in 20/min an address and 10/min an account; sign-up 10/h; AI 20/min, uploads 20/min, exports 30/min a user | `config.py`, `security/rate_limit.py` | 429 `too_many_requests` |
| A plan | documents, AI operations, templates, storage | `billing/plans.json`, `services/entitlements_service.py` | 402 `plan_limit` |
| Background jobs | timeouts, retries, cancellation: JOB-001, in progress | `jobs/` | -- |

## Errors

Every error is `{code, message, details, request_id}` (SEC-019, `tests/test_error_envelope.py`).
- **The message is written for people:** never a trace, an exception's own text, or what was sent.
- **A crash is a plain 500.** The log keeps the trace, with the request id.
- **A request that isn't valid** says where and what (`details.errors`: `loc`, `msg`, `type`), never the values, so
  a password sent back can't appear. The conflict resolutions of a format request used to answer with pydantic's
  own report, the values in it; they answer the same way as any invalid request now.
- **Checked over every route in the OpenAPI schema**, signed in and not, plus the errors no route chooses: an
  unknown path, a wrong method, a body too large.

## The security regression suite

`python -m pytest -m security` (TEST-030) runs it on its own; CI runs it as its own step, then everything else once.
It holds:
- the malformed-file corpora: Word (SEC-010), PDF (SEC-011), pictures (SEC-012);
- the link and field policies (SEC-014, SEC-015);
- prompt injection, the upload checks and limits, document authorization;
- `tests/test_security_suite.py`, which reads the API's own OpenAPI schema, so a route added later can't go
  unchecked:
  - IDOR: every route that takes an id answers a user of another workspace exactly as it answers an id that
    doesn't exist (404, the same body), and leaves the owner's document, picture, job and template as they were.
    A route without a request in its table fails the suite.
  - Anonymous requests: every such route needs a signed-in user.
  - CSRF: every write refuses another site's Origin before it reaches the route. The app's own site and requests
    without an Origin get through.
- Mutation-checked: removing any of the document, asset, job and template ownership checks, or the cross-site
  check, fails it.

## Repository hygiene

- The repository is public, so the secret scan runs before every push.
- `backend/.env` is ignored and never printed.
- Tests never touch the real database: the suite refuses a non-test database URL.
- Playwright traces (`frontend/test-results/`) hold throwaway-session cookies and are ignored by git.
