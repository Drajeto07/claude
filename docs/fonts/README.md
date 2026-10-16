# Fonts and multilingual rendering

Brief §50-53, tracker Phase 11. Code: `backend/app/export/font_catalogue.py`, `font_resolver.py`, `rtl.py`,
`backend/app/bidi.py`, and the per-script parts of `pdf_export.py` and `docx_export.py`.

## The catalogue (FONT-001)

`font_catalogue.catalogue()` reads, once, every installed font file of a family the exports know (the PDF export's own
families in `export/fonts.py`, and the families other scripts fall back to: Nirmala UI, Leelawadee UI, Microsoft
YaHei, SimSun, Yu Gothic, MS Gothic, Malgun Gothic, the Noto families…) with fontTools: its cmap's characters, the
scripts it covers (all of a script's sample: `SAMPLES`), its units per em, ascent and descent, and whether its licence
lets it be embedded (OS/2 fsType: 2, restricted, is never used in a PDF).

## The resolver (FONT-002)

`font_resolver.resolve(text, family)` -- deterministic, never the AI's choice:

1. the text is split into runs by script (ISO 15924; digits, punctuation and spaces join the run they're in);
2. each run is drawn by the paragraph's own font when it has every letter of the run, else by the first installed,
   embeddable font of the script's chain (`SCRIPT_FAMILIES`) that has them all, else by the one with the most;
3. a character the run's font lacks -- a symbol, an emoji -- goes to a font that has it (Segoe UI Symbol, DejaVu Sans
   first); with none, it is missing.

A document mixing German, English, Bulgarian and Arabic is drawn in as many fonts as it needs.

## The PDF (FONT-003)

- Markup: each run's parts another font must draw are wrapped in that font (`_fonted`).
- Shaping: a paragraph holding Arabic, Hebrew, Devanagari or Thai is shaped with HarfBuzz (`uharfbuzz`; reportlab's
  `style.shaping`): Arabic letters joined, Devanagari conjuncts formed. Without HarfBuzz on the server, that is said.
- Right to left: reportlab's bidi goes through a module named `rlbidi`, which isn't on PyPI; `app/bidi.py` stands in
  (registered in `app/__init__.py`): UAX #9 without explicit embeddings -- types, weak types, bracket pairs (N0),
  neutrals, levels, reordering, mirroring -- checked against python-bidi. reportlab 5.0.1 orders words right to left
  only in a paragraph of one font and no shaping, so a paragraph led by right-to-left text is an `RtlParagraph`
  (`export/rtl.py`): reportlab breaks its lines (shaped, so widths are exact), each line's words are put in the order
  they're seen, and each line is drawn aligned to the right (unless set otherwise; justified lines stay justified but the
  last). A right-to-left list item's label leads, on the right.
- Notes: characters no installed font draws (`export.pdf.script`, with them); Devanagari and Thai words, which look right
  but can't be copied out as text -- their joined letters have no text of their own in the PDF (`export.pdf.text_layer`).
- The read-back check reads the PDF with pdfminer (pypdf drops a line's left-to-right words when it holds right-to-left
  ones), normalises Arabic's joined forms (NFKC), puts right-to-left lines back in reading order, and leaves Devanagari
  and Thai words out of the comparison.

## Word (FONT-004)

Each run holding East Asian text gets `w:rFonts w:eastAsia` (the run's font if it covers the script, else the script's
first family) with `w:hint="eastAsia"` and `w:lang w:eastAsia`; complex-script text (Arabic, Hebrew, Devanagari, Thai)
gets `w:rFonts w:cs`, `w:lang w:bidi`, `w:bCs`/`w:iCs` for bold and italic, and `w:rtl` for right-to-left scripts. A
paragraph led by right-to-left text gets `w:bidi` unless its style sets a direction.

## Fonts on the server

The PDF can only use fonts installed where it is made (`PDF_FONT_DIRS`, then the system's folders). CI installs
fonts-dejavu-core (Latin, Cyrillic, Greek, Arabic, Hebrew); a production image that serves Devanagari, Thai or CJK needs
e.g. fonts-noto-core and fonts-noto-cjk. Whatever isn't installed is reported on each export, never drawn as boxes
silently.

## Stand-ins for a missing font (FONT-005)

One list for the PDF export and the editor (`app/export/fonts.py`: `METRIC_COMPATIBLE`, `_FALLBACKS`, the kind
hints; `fallback_stack`). What stands in for a font that isn't installed, best first:
1. the fonts made with its widths, so its lines break as they would: Carlito for Calibri, Caladea for Cambria,
   Liberation Sans or Arimo for Arial (and Helvetica), Liberation Serif or Tinos for Times New Roman, Liberation
   Mono or Cousine for Courier New;
2. then the best installed fonts of its kind (sans, serif, mono -- told by its name: Constantia is a serif).

A PDF export draws the first installed (`resolved_family`). The editor writes the whole list as the CSS
font-family -- `"Calibri", "Carlito", "Arial", "Liberation Sans", ..., sans-serif` (`editor/fontStack.ts`) -- so
the browser takes the first it has, as the export does. The editor reads the list from
`frontend/editor/fontFallbacks.json`, written by `python -m scripts.export_font_fallbacks`;
`tests/test_font_fallbacks.py` fails when that copy is out of date. The saved document keeps only the font's own
name.
