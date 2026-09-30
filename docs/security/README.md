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

- **Word import:** only safe addresses (http, https, mailto...) become links (`parsers/docx_inline.py::safe_href`).
  Others (javascript:, file:, UNC) are kept as plain text and reported (`docx.link.unsafe`).
- **Markdown:** markdown-it refuses javascript:, vbscript:, file: and non-image data: links.
- A model-level policy for every href, whoever sends it, is SEC-014 (open).

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

## Repository hygiene

- The repository is public, so the secret scan runs before every push.
- `backend/.env` is ignored and never printed.
- Tests never touch the real database: the suite refuses a non-test database URL.
- Playwright traces (`frontend/test-results/`) hold throwaway-session cookies and are ignored by git.
