# Security notes

These are the security decisions the code relies on, with pointers to where each is enforced. The full list of open
and done items is in the tracker's SECURITY rows.

## Values that reach styles

Formatting rule values are checked per property before they can reach CSS, Word or PDF (SEC-022,
`docs/formatting/README.md`). Before this, `center;background-image:url(…)` sent as an alignment through the style
endpoint or an instruction ended up in every viewer's editor. The Mark model validates a run's font name and
colours for the same reason.

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
  copy XML in place of text it changed, or write one original block for two elements.
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
