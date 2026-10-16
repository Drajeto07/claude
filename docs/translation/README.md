# Translation

Translate without destroying format (brief §45-52, §87, §94-96; tracker Phase 10). Code: `backend/app/translation/`,
`backend/app/services/translation_service.py`, `frontend/editor/panels/TranslatePanel.tsx`.

## Segments and tags (TRAN-001)

A document is never translated as one string. Each paragraph, heading, caption, list item and table cell is a
segment (`translation/segments.py`) that keeps its element id, its path in it (`item/<id>`, `cell/<id>`), its style
reference, its languages, its status and its provider. Formatting travels as tags the translator moves with the words
but never sees the meaning of:

| In the text | Tag | Comes back as |
| --- | --- | --- |
| a run with marks (bold, a link, a colour…) | `<mN>…</mN>` (N: the run's index) | the run's marks, on whatever words the tag holds |
| code, a web or e-mail address | `<xN/>` | its text and marks, untouched (never translated) |
| a line break | `<br/>` | a line break |
| `&`, `<`, `>` | `&amp;`, `&lt;`, `&gt;` | the characters |

A translation is parsed back into runs (`untag`); a tag that isn't the segment's, opens inside another, isn't closed or
closes nothing -- or any markup the segment didn't have -- is refused.

Not translated, and named in the answer or report: code blocks; blocks nested in a quote, a list item or a table cell;
blocks holding Word content placed by its position in the text (fields, bookmarks, comments: translating moves the words
under them).

## Providers (TRAN-002)

`TranslationProvider.translate(segments, source, target, glossary)` gives each segment's tagged translation by id.
`TRANSLATION_PROVIDER` chooses: `ai` (the default; `AITranslator`, batches of 40 segments / 6,000 characters, the text
in an untrusted-data wrapper, system rules to keep every tag, number, unit, identifier and glossary term and to add or
drop nothing) or `pseudo` (`PseudoTranslator`: every letter accented, everything else kept -- no AI, for tests, the E2E
server and demos). A batch that fails is `TranslationUnavailable` (503 `translation_unavailable`); a segment the answer
leaves out is "failed". Translation runs within the AI's call and time budget, and is metered by its characters, not as
AI operations.

## Validation (TRAN-003)

Every answer is checked (`translation/validation.py`) before anything is done with it. A translation may change every
word, never a fact:

- tags: each of the source's, as often, and parseable;
- numbers: the same digit groups, however separated (3.14 → 3,14, 1,000 → 1 000, 17/05/2024 → 17.05.2024), none
  changed, added or dropped;
- percentages: as many `%` signs;
- units after a number, by what they measure (mg → мг is fine, mg → g is not);
- identifiers (letters and digits: ISO-9001, AB-123, v2.1) exactly;
- locked glossary terms: the term's translation wherever the term appears;
- length: between a third and three times the source's (from 24 characters).

A segment with a problem stays as it was ("invalid"), and the problem is said in words -- never with its text in a log.

## Glossary and language (TRAN-004, TRAN-007)

`Document.glossary` (`PUT /documents/{id}/glossary`): terms with their translation, domain, `locked` (always so),
`caseSensitive`, and optional source/target languages limiting where they apply. `translation/language.py` detects a
text's script (ISO 15924) and direction from its letters and its language from letters only one language of the script
uses and its commonest words (Bulgarian, Russian, Ukrainian, Serbian; English, German, French, Spanish, Italian,
Portuguese, Dutch, Polish, Romanian, Turkish; Greek, Hebrew, Arabic, Hindi, Thai, Chinese, Japanese, Korean); unsure,
it says so. `GET /documents/{id}/language` gives it with what the user set (`PUT …/language`, which overrides
detection). The target language is always explicit.

## Proposals (TRAN-005)

`POST /documents/{id}/translate` with block ids (or one block and `selection` {start, end} of its text), the target and
optionally the source. The provider is called with no lock held; each block whose translation (or part of it) passes
becomes a `replace_content` proposal (category `translation`, source `translation`) with the block as it would be --
same id, kind and style, each run's formatting where its words went -- and the problems of any part left as it was.
Nothing changes until it is accepted; accepting checks the block is still as it was (else 409 `stale_proposal`), keeps
its id, place, style and provenance, and is an ordinary undoable change ("Translated a block into …"). A newer
translation of a block replaces the one waiting for it.

## Translated version (TRAN-006)

`POST /jobs/translate-document` {documentId, targetLanguage, sourceLanguage?}: a new document -- "Title (Language)",
`metadata.translatedFrom` (the original's id, revision, title, languages, provider), `metadata.language` the target --
whose pictures are its own copies, and whose report (stage `translation`) says it is AI-assisted
(`translation.ai_assisted`), which blocks kept original text and why (`translation.kept_original`), and which weren't
translated (`translation.not_translated`). The original is never changed. Its first version reads "Translated from “…”
into …".

## Metering (TRAN-009)

Translation characters (the text sent, tags left out) are a plan unit: reserved before the provider is called and given
back if it fails (`UsageReservations.held`); past the month's `maxTranslationCharacters` a translation is refused (402
`plan_limit`).

## The Превод panel (TRAN-008)

The rail panel shows "AI-assisted translation — review required." at all times, the document's language (detected, or
chosen), the language to translate into, "Translate selection" (the cursor's block, the blocks the selection touches, or
the selected part of one block's text: `editor/translationTarget.ts`), "Create translated version" (opens the new
document), the translations waiting for review -- original against translation, with what was left as it was -- and the
glossary.
