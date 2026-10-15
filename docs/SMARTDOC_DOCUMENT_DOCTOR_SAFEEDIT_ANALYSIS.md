# Document Doctor + SafeEdit -- initial technical analysis

Status: **analysis only** (2026-10-14, D-013 context). No implementation is proposed here beyond a small,
measurable MVP; the editor (E2) stays the current priority. Nothing in this document promises that a document
"cannot be damaged": it defines what is checked, how it is measured, where the system must refuse, and what a
person must review.

## 1. The promise, stated so it can be tested

Document Doctor finds layout and structure defects in a Word file and proposes repairs. SafeEdit is the contract
every repair obeys:

1. **The words don't change.** The repaired file's word sequence equals the original's, as read by an
   independent reader of the file's XML (not by the code that wrote it). Any difference: the repair is undone and
   reported. (Exception, declared per repair: typed list numbers becoming Word numbering -- section 4.2.)
2. **What wasn't repaired is untouched.** Blocks outside the repair are copied from the original file as they
   were, byte for byte.
3. **The file stays a valid Word file.** Every part parses, every relationship resolves, every style and list
   referenced exists.
4. **Every change is visible before it happens** and applied only when accepted; any accepted change can be
   undone; the original file is always downloadable.
5. **When in doubt, refuse and ask** (section 9).

Each of the five is a check the system runs on every repair, not a description of intent.

## 2. What already exists (backend, measured)

| Capability | Where | What it gives Doctor/SafeEdit |
| --- | --- | --- |
| Word import with tracked changes resolved like Word | `parsers/docx.py`, `docx_revisions.py`, `docx_inline.py`, `docx_tables.py`, `docx_pictures.py`, `docx_styles.py`, `docx_comments.py` | the model to analyse; accept/reject all as the person chooses |
| Independent text of a Word file | `fidelity/docx_source.py` | SafeEdit rule 1: reads the XML itself, fields by result, notes, text boxes, accepted changes |
| Word-sequence content check | `fidelity/content.py` | "verified" only when the two word sequences are identical; differences located (missing/added/changed/moved) |
| Token-level check of AI output | `fidelity/text_check.py` | numbers, units, negations, punctuation: any change fails |
| Fidelity report (import/edit/export) | `fidelity/report.py`, `imports.py`, `exports.py`, `docx_detect.py` | every feature changed, approximated, kept-for-export, left out or refused -- never silent |
| Four-axis round trip (content, structure, formatting, metadata) | `fidelity/round_trip.py` | before/after comparison of two Word files, each axis on its own |
| Writing into the original package | `export/docx_export.py`, `export/provenance.py` | unchanged blocks (by fingerprint) copied as they were: fields, content controls, unknown XML included -- SafeEdit rule 2 |
| Package validator | `export/package_check.py` | SafeEdit rule 3, independent of the writer |
| Document Health: 21 deterministic checks | `formatting/health.py`, `accessibility.py` | fonts, heading sizes, spacing, numbering, lists, hierarchy, alignment, page breaks, tables, broken tables, captions, links, direct and repeated formatting, empty paragraphs, alt text, hidden text, language, layout, sections, kept-from-original |
| Deterministic fixes as proposals | `formatting/health_fixes.py`, `proposals.py`, `repair.py` | each fix a reviewable change with the block as it would be; applied only to the block as checked (fingerprint), else dropped |
| Review UI | Review panel, Repair section, proposal cards (editor) | per-change accept/reject/show; whole categories except content |
| Clean copy | `CleanCopySection` / API | a new document with chosen removals; the original stays |
| Version history, compare view | `services/version_history.py`, `/compare` | every accepted change is a version; before/after side by side |
| Corpus with committed expectations | `tests/fixtures/word` (37 Word files: features a01–a15, a real paper r01, more) with `.expected-loss.json` and `.expected-fidelity.json` | regressions fail until the manifest is rewritten on purpose |
| Word's own ground truth | the Word label harness (list numbering as Word draws it) | numbering repairs checked against Word, not against ourselves |

**Baseline today** (committed manifests, 37 fixtures): 111 independent word checks (import, Word export, PDF
export) -- **110 verified, 1 changed** (one multilingual file's PDF on Windows: a script without a covering
font). Reported items: 82 kept and editable, 94 kept for export but not editable (fields, bookmarks, text
effects, content controls, floating pictures, tab stops, TOC...), 37 approximated (mostly in PDF: fields,
character spacing, notes, alt text, tab stops), 2 left out (PDF comments; symbol-font characters on import).
The Word export writes into the original package in all 37.

What does **not** exist yet: authoring *new* tracked changes in Word output (existing ones can be kept); a
defect corpus with labelled ground truth; detection of digital signatures and macro-enabled packages as
refusal reasons; a "repair session" that bundles detection → proposals → verification → repaired file.

## 3. Which defects can be detected reliably

Reliability is graded by how the check works, not by hope.

**A -- deterministic, high confidence** (rules over the file's own structure; false positives rare and
explainable; candidates for one-click repair after review):
- package defects: unparsable parts, dangling relationships, undefined styles/lists (`package_check`);
- typed numbering ("1.", "2.1") in plain paragraphs instead of Word numbering; broken list sequences;
- heading level jumps (H1 → H3), headings with body styling, body text styled as headings by direct formatting;
- empty paragraphs used as spacing or as page breaks;
- the same role (body, H2, caption) in several fonts/sizes/spacings; direct formatting that repeats the style;
- tables and pictures wider than the text area; ragged tables (rows with different cell counts);
- malformed or unsafe link targets (as written -- links are not visited);
- pictures without alt text; hidden text; text whose language differs from its mark;
- sections set up almost alike (a margin off by 0.01 cm).

**B -- heuristic, medium confidence** (proposals only, always reviewed, never bulk):
- a short bold line that "looks like" a heading; a paragraph that "looks like" a caption;
- inconsistent list styles that may be intentional;
- PDF-derived structure (the conversion's own confidence is shown per aspect).

**C -- needs meaning (AI or a person)**: what a picture shows (alt text), whether a heading's wording fits,
tone. Never repaired automatically.

## 4. Fixing layout without changing text

### 4.1 Operation classes

| Class | Examples | Text invariant |
| --- | --- | --- |
| Style-only | fonts, sizes, spacing, alignment, indent, table width, picture width | word sequence identical -- **strict** |
| Structure, text-neutral | empty paragraphs → spacing / page break; direct formatting → style; heading level by style | word sequence identical -- **strict** (empty paragraphs hold no words) |
| Structure, label-changing | typed "1." → Word numbering | words identical **except** the typed labels, which must equal the labels Word will draw (checked with the Word label harness logic), position by position |
| Content | any change of words | **not Doctor's**; only through the content category, one by one |

### 4.2 Verification pipeline (per repair, then for the whole file)

1. Fingerprint the target blocks (already done for proposals).
2. Apply the repair to the model; export **into the original package** (unchanged blocks copied).
3. Read the result back with the independent reader; run the content check against the original file.
4. Run `package_check`; run the round trip's structure axis: only the declared blocks may differ.
5. Any failure → the repair is undone automatically, the proposal is marked "couldn't be applied safely",
   and the reason is shown. Nothing partial is kept.

## 5. Before/after comparison

- **Per change** (exists): the block as it is and as it would be, in the proposal card.
- **Per file** (to build on `round_trip.py`): a summary with four lines -- *Words: identical (N words checked)*;
  *Structure: K blocks changed as listed, everything else identical*; *Formatting: what changed, by role*;
  *Metadata: unchanged / removed as chosen*.
- **Visual** (optional, later): render both files to page images and highlight the regions that changed; used
  to show that *untouched* regions are pixel-identical, not to judge the repairs themselves.
- The original file is always one click away; the compare view shows any two versions side by side.

## 6. Preserving tables, images, headings, lists, notes, numbering, styles

Mechanism: the original package is the base of every output; only repaired blocks are rewritten, and only in
the properties the repair names. What the model can't hold (fields, bookmarks, content controls, text effects,
floating pictures, TOC, tab stops) is **kept for export** and reported, never dropped silently. Per feature:

| Feature | Today | Doctor rule |
| --- | --- | --- |
| Tables | structure, merges, widths, look round-trip; style look partly approximated | repairs touch width/borders only; a ragged table is flagged, not rebuilt |
| Images | inline round-trip; floating/wrapped kept for export | never moved or resized unless the repair is "fit width" on that picture |
| Headings | style and level kept | level changes proposed one by one when cross-references or a TOC point at them |
| Lists / numbering | Word numbering kept; labels verified against Word | renumbering refused where REF fields point at numbered paragraphs |
| Notes | footnotes/endnotes kept; numbering preserved | not touched by layout repairs |
| Styles | modified styles round-trip | repairs prefer changing a style to adding direct formatting; style changes are listed per role |

## 7. Review and approval (UX)

1. **Check** -- the person uploads a file (or opens a document) and runs *Check document*. Result: a short list
   grouped by kind (numbering, styles, tables, links, structure, accessibility), each with severity, how sure the
   check is (A/B/C), and *Show* in the document.
2. **Propose** -- *Propose repairs* for one kind or for all A-grade findings. Each proposal shows the block before
   and after and states "text unchanged" (verified, not assumed).
3. **Decide** -- accept or reject per change; accept a whole A-grade kind at once; B-grade only one by one;
   content never in bulk. Nothing changes before acceptance; every acceptance is a version and can be undone.
4. **Deliver** -- *Download repaired file* with the file-level summary (section 5) and a badge only when all
   checks passed: "Words identical · 12 blocks restyled · nothing else changed · valid Word file". Where any
   check didn't pass, there is no badge, and the reason is said plainly.
5. **Optional, later**: deliver the repairs as Word tracked formatting changes, so a recipient reviews them in
   Word itself (needs new export code).

## 8. Proving reliability

**Test layers**
- *Invariant tests* over the whole corpus: for every fixture and every applicable repair -- content check
  verified, untouched blocks byte-identical in the output package, `package_check` clean, round-trip structure
  differs only where declared. Run in CI on every push.
- *Defect corpus* (new): small Word files each carrying known, labelled defects (ground truth in a manifest:
  defect kind, location), made in Word itself where possible, plus the existing 37 fixtures as "no defect"
  controls for false positives.
- *Word as the judge*: a sample of repaired files opened in Word (the label harness) -- no repair prompt, list
  labels as expected, page count within ±1.
- *Real documents*: anonymised, with consent, never production user data without the owner's explicit decision.

**Metrics (reported per defect kind, on the labelled corpus)**
- detection precision and recall;
- repair success rate (accepted repair passed all checks);
- **text preservation: 100% required** -- any miss blocks the release of that repair kind;
- untouched-block identity: 100% required;
- valid package: 100% required; Word opens without repair prompt: 100% on the sample;
- time per file (p50/p95) for files up to the upload limit.

## 9. When the system must refuse and ask a person

- The import's own content check is not "verified" (the model may already differ from the file).
- The file has pending tracked changes and the person hasn't chosen accept/reject.
- The file is digitally signed (any change invalidates the signature) -- to detect; today not detected.
- Macro-enabled or encrypted/IRM-protected packages -- refuse, don't open.
- The repair would touch a block holding preserved-but-not-editable content (fields, content controls,
  equations, embedded objects, SmartArt) -- flag only.
- Renumbering where cross-references (REF/PAGEREF fields) or a TOC point at the numbered items.
- B-grade findings: never automatic.
- Any post-repair check fails: the repair is rolled back and reported.
- Files above the size/complexity limits (the existing upload and zip-bomb guards).

## 10. Where AI is really needed -- and where it isn't

Without AI: all of section 3 A, all verification, all repairs in section 4, the before/after summary, the
corpus and metrics. **The MVP needs no AI and no paid service.**

With AI (only as proposals, through the existing token-level text check, and only after the owner enables a
provider -- D-007, no new costs without approval): classifying B-grade roles (heading vs bold line, caption vs
paragraph), suggesting alt text for a person to accept, explaining a finding in plain words (exists).
AI never scores, never fixes formatting directly, never changes words without the content check.

## 11. A small, measurable MVP ("Doctor v0", Word only)

Scope -- five A-grade repairs plus three flag-only findings:

| # | Defect | Action |
| --- | --- | --- |
| 1 | Empty paragraphs used as spacing / page breaks | repair → paragraph spacing / page break |
| 2 | One role in several fonts/sizes/spacings | repair → the role's dominant style |
| 3 | Direct formatting repeating the style | repair → removed |
| 4 | Tables/pictures wider than the text area | repair → fit width |
| 5 | Typed numbering in plain paragraphs | repair → Word numbering, labels checked against Word |
| 6 | Heading level jumps | flag only |
| 7 | Pictures without alt text | flag only (a person writes it) |
| 8 | Malformed links | flag only |

Deliverable: upload .docx → findings → proposals → repaired .docx + summary, using the existing editor's Review
panel (no new editor work). Exit criteria: on the labelled corpus, 100% text preservation, 100% untouched-block
identity, 100% valid packages; precision ≥ 95% for the five repairs; recall reported, no target promised.

**Comparison with other tools** (owner's approval needed for any paid licence or trial): run the same defect
corpus through Word's own Accessibility Checker and Inspect Document, and a consistency checker for Word (e.g.
PerfectIt, trial) where approved; measure defects found, defects fixed, words changed (our independent reader on
their outputs), files Word opens cleanly. Report the numbers as measured, including where others do better.

## 12. Estimated effort and order (after E2)

1. Defect corpus + labelled manifest + invariant test harness (largest share; it is what proves the rest).
2. Repair session API (detect → propose → verify → file) on top of health/proposals/export.
3. File-level before/after summary on `round_trip.py`.
4. Refusal detection: signatures, macro/encrypted packages, REF/TOC targets.
5. The five repairs' verification pipeline (section 4.2) and UX wording.

Open questions for the owner: the size limit for Doctor v0 files; whether real (anonymised) documents may be
added to the corpus and from whom; whether a competitor trial may be used.

---

## 13. Doctor v0 -- what was built and what it measured (2026-10-15)

Prototype behind a feature flag (the editor shows it only with `?doctor=1`; `DOCTOR_ENABLED=false` turns the API
off). Not a finished product.

**Flow.** Upload a .docx -> *Check the document* (findings, each with where it is and why) -> choose repairs
(nothing is chosen by default) -> editor repairs are proposals accepted one by one (Review cards) -> *Check the
repaired file* -> *Download* only when verified. The original Word file is never written to (stored source,
checked by checksum); the repaired file is a new download, counted as an export.

**Code.** `app/doctor/safe_edit.py` (the five checks), `app/doctor/doctor.py` (refusals, findings, safe
proposals, touched blocks, build + verify), `app/doctor/word_repairs.py` (repairs made in the file itself),
`app/api/doctor.py` (4 routes), `frontend/editor/panels/DoctorPanel.tsx`.

**SafeEdit checks on every repaired file**, both files read independently: body words; header/footer words;
every block nobody repaired byte-identical and in order; preserved features (bookmarks, fields, drawings,
legacy pictures, embedded objects, content controls, section breaks, note references, comments, tracked
insertions/deletions, equations, links) none fewer; a valid package. Each check is proven to catch its failure
by a test that damages a result on purpose (tests/test_doctor.py).

**Two kinds of repair.**
- *In the Word file itself* (new): empty paragraphs used as spacing (removed; about the same space given to the
  neighbouring paragraph as spacing, the property inserted where the schema requires it), inline pictures and
  tables wider than their section's text (scaled). Chosen ones are made in the exported file; a repair whose
  blocks don't line up exactly with the original is skipped, never guessed.
- *In the editor* (existing Document Health fixes, safe kinds only): page breaks, fonts, repeated formatting,
  layout, empty paragraphs the model holds. A model repair is dropped when a repair in the file covers the same
  block (the smaller edit wins), because SafeEdit caught the export rewriting a neighbouring block when the
  editor rewrote a table (d13).

**Refused, with the reason shown:** no Word file; the stored file unusable; the import's own word check not
passed; tracked changes undecided; digitally signed; macros; a damaged package; and -- found by measuring -- a
file that the export would change even with no repair (a06: the app won't write back a link to a local file).
Per block: a repair of a block holding a preserved feature is left for the person.

### Measured on the labelled defect corpus (13 files, tests/fixtures/doctor, ground truth by construction)

| Defect | Planted | Repaired by v0 | Note |
| --- | --- | --- | --- |
| Empty paragraphs used as spacing | 11 | 10 | the one next to a table is left on purpose (Word needs it) |
| Table wider than the text | 2 | 2 | |
| Picture wider than the text | 1 | 1 | the editor shows it at 100 % width, so its model never saw it |
| Page breaks doubled / after the content | 2 | 2 | |
| A paragraph in another font | 4 | 0 | **gap**: a whole-paragraph font is imported as a paragraph rule, which the font fix doesn't clear |
| Formatting repeating the style | 3 | 0 | **gap**: the importer folds it away; the Word file keeps it |
| Clean control | 0 | 0 proposals | no false positive |
| Signed / macros / tracked changes | -- | refused | all three |
| Bookmark in an empty paragraph, field in an off-font paragraph | -- | kept | |

Every repaired file in this corpus and in the 37-file Word corpus came back verified; every other file was refused
for a stated reason (a06, a07, d10-d12). Detection precision on this corpus: no wrong proposal. Recall: 15 of 23
planted defects (65 %), 15 of 15 for the four kinds v0 repairs (minus the one left on purpose by rule).

These are small, synthetic files: the numbers say the checks hold on what they cover, not that v0 finds every
real-world defect. Next: the two gaps (paragraph-rule fonts, repeated formatting) as repairs in the file, real
anonymised documents (owner's decision), a competitor comparison (owner's approval if it costs anything).

### The one content check out of 111 that wasn't verified (a11-multilingual, PDF on Windows)

Investigated with the page rendered and every glyph's position measured:
1. **A real defect, fixed**: a right-to-left paragraph (Word's `w:bidi`) starting with a Latin word
   ("Arabic: ...", "Hebrew: ...") took its direction from that first letter, so on a machine with text shaping
   its words were drawn in reverse order. The PDF export now honours the paragraph's own direction
   (`pdf_export._for_text`); Hebrew reads back exactly; regression tests in tests/test_multilingual.py fail
   without the fix.
2. **A remaining, documented limit**: in two Arabic words the PDF's text layer gives the Persian yeh (U+06CC) for
   the Arabic yeh (U+064A) -- the same glyph in those positions, so the page looks right but copied text differs.
   The check rightly stays "changed" for this file; the Word export is exact.
