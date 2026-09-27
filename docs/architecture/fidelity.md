# Fidelity: what an import, an edit or an export changed

Brief §17 and §90. The platform never says "No content changes" unless it proved it, and it names everything it
changed, approximated or left out.

## The Document Fidelity Report

The report model lives in `backend/app/fidelity/report.py`. Each `FidelityItem` has:
- a stable feature key (`docx.hidden_text`, `export.pdf.script`...);
- a **policy class**: `detected_preserved`, `detected_not_editable` (kept for export only), `lossy`, `unsupported`,
  `blocked` or `not_detected`;
- a reason for people;
- a count;
- an example of the text it concerns (`sourceState`);
- `contentChanged` when words, pictures or other content were lost, not only their look.

The report's content fields are:
- `reviewCount`: items a person should look at, i.e. lossy, unsupported or blocked ones;
- `contentLossCount`;
- `contentStatus`: `verified`, `changed` or `unverified`.

## The content check

`compare_words` (`fidelity/content.py`) compares the source's words with the result's, in order. It reports
`verified` only when the two are identical. An export to PDF may add words (page numbers, headers), so it passes
when the source's words appear in order.

The source is read independently of the importer:
- **Word files:** `fidelity/docx_source.py` mirrors only the importer's deliberate choices: accepted revisions, field
  results, linear math, drop caps, text boxes after their paragraph, note labels.
- **Pasted or Markdown text:** `fidelity/text_sources.py` counts the words a reader sees. Syntax, link addresses and
  a picture's description are not counted.
- **PDFs:** the check compares against the text read from the PDF.

Header and footer words are checked as a multiset. Each import path attaches its report as `Document.importReport`.

## What the importer changes

Two sources name what the Word importer changes without keeping it (FID-002):
- `fidelity/docx_detect.py` reads the file itself, styles included. It finds hidden text, caps, underline variants,
  content controls, custom properties and sensitivity labels (never their values), crop and rotation, table
  geometry, bullets in cells, right-to-left text, autolinks, charts and SmartArt, and what sections change.
- The importer's own `Notes` (`parsers/docx_inline.py`) record what it meets while reading: empty spacing paragraphs,
  links with unsafe addresses, list labels it can't express, shapes, embedded objects, and more.

The Markdown importer reports pictures it doesn't fetch (FID-006).

## Exports

`fidelity/exports.py` collects what an export approximates or leaves out (a `collecting` context around
`build_docx` / `build_pdf`). It then re-reads the written file:
- a Word export must hold exactly the document's words;
- a PDF must hold every word in order.

The export job returns this report and the UI shows it under Download.

## The capability matrix

`backend/app/capabilities.py`, served at `GET /api/v1/capabilities`, lists every feature with:
- its import, edit, export and round-trip support;
- the policy class;
- the report keys that name it;
- the tests behind each claim.

`tests/test_capabilities.py` ties it to the code both ways:
- every key the code reports is described;
- every described key is reported somewhere;
- every cited test exists;
- nothing claims a clean round trip without a test.

## In the editor

- **The Проверка panel** (`frontend/editor/panels/FidelityPanel.tsx`) shows the verdict, where the words differ, and
  every item. It also has a **While editing** section: formatting the editor holds that the document can't keep,
  which `reconcileWithIds` names as `notes` on every save.
- **The status bar** shows the import verdict ("No content changes" only when proven and nothing else was lost),
  the review count, and "N formatting changes not kept".
