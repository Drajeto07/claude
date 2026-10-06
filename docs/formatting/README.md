# Formatting rules

The formatting engine is `backend/app/formatting/engine.py`. An element's look is never stored on it: it is resolved
from `Document.formattingRules`.

A `FormattingRule` has a target, a property, a value, a unit, a priority and a source. The target is a kind of
block ("Paragraph", "Heading 1", "Table", "Image"...), one element's id, or "Document" for page settings.

## Priorities

The lowest number wins (`formatting/priorities.py`). A live override is what a person sets on one element or on the
page, with the toolbar, the Properties panel, page settings or the editor's own formatting. It wins over
instructions, which win over templates and a source document's own formatting, which win over the defaults
(`render_spec.py`).

A Word file's own formatting is complete (FMT-004): what its styles and document defaults leave unset is what Word
draws there -- no bold or italics, no spacing, single lines, left aligned, no indent, 10 pt Times New Roman
(`docx_styles.py::as_word_draws`) -- so the defaults (a bold heading, 8 pt after a paragraph or a table, a quote
indented 1 cm, small italic captions) never stand in for what the file leaves to Word. They still shape a document
made here or pasted in.

Each kind of block takes from the body text what `render_spec.FROM_BODY` says -- as a Word style based on Normal
does -- in an imported document too (TEST-022): a kind's value that is the body text's own isn't recorded as the
kind's (`docx_styles.py::inherit_from_normal`), so a template that changes the body text changes lists, tables,
captions, quotes and headings with it, here as in Word. And a Word export written into the original file writes
every kind's Word style once the body text's look changed (`_define_styles`), so Word shows each as it looks here.

Within one tier, a rule for one element beats a rule for its kind. `recompute_styles` rebuilds:
- `resolvedStyles`: one CSS map per kind, and per element that has rules of its own;
- `settings`: the page;
- each element's `styleRef`.

## Where rules come from

- **Templates and Format by Example:** a `StyleSystem` (`style_system.py`), validated field by field and compiled
  into rules.
- **Instructions (AI):** coarse rules plus targeted `set_style` operations.
- **The toolbar and Properties panel:** `PATCH /documents/{id}/elements/{element}/style`. Page settings use
  `PATCH /documents/{id}/settings`.
- **The editor itself (EDIT-008/009):** alignment typed with a shortcut or pasted onto a paragraph or heading, and a
  pasted picture's width. A content save (`PATCH /documents/{id}/content`, or `PUT` with the whole document) carries
  these as `styles` (`DirectStyle`). They are stored
  as the element's own live override, without a revision entry, because they belong to the typing saved with them.
  A block split off one keeps its alignment, as in Word.

## Format by Example (FMT-001..003)

- **What a reference's look holds (FMT-001):** its text styles per kind (paragraph, headings 1-6, lists, tables,
  captions, quotes, footnotes, code -- fonts, sizes, weight, colour, alignment, spacing, indents), its page setup and
  margins, its pictures' width and alignment, a header or footer that is only page numbers -- and, in
  `StyleSystem.structure`, what a rule can't carry: its tables' border (the one most of its tables share), header-row
  shading and bold (bold only when the header text really is), the levels its bulleted and numbered lists count by (the
  ones most list items use), and its heading numbering. `formatting/structure.py` sets the structure on the document's
  tables, lists and heading numbering when the template is applied; a template that sets none of it changes none of
  them. Its own header and footer text belongs to that document and isn't copied (said in the notes).
- **The AI only maps (FMT-002):** where a reference doesn't use Word's heading styles, the AI may say which short
  paragraphs are headings and their levels (`ai/semantic_labeling.py`); its answer is used only when it names known
  paragraphs, gives levels 1-6, doesn't call most paragraphs headings, and its levels fit the headings' sizes (a level-1
  heading is never clearly smaller than a level-2 one). Otherwise headings are found by their look, and the notes say
  how they were found. Either way the engine, not the AI, works out every style.
- **Before and after (FMT-003):** `POST /documents/{id}/style-preview` tries a StyleSystem on the document -- the real
  engine on a copy -- and gives the resolved styles and page settings now and with the look, what changes in words
  ("Table: font Arial → Georgia", "Page: page size A4 → Letter", the tables and lists it changes, heading numbering), and
  saves nothing. The Templates panel shows it ("Now" / "With this look") before a reference's look is applied or saved.

## Paragraph properties (DOCX-014)

Besides fonts, alignment, spacing and indents, a rule can set a paragraph's right indent (`indentRight`), its
background colour (`shading`), Word's pagination controls (`keepWithNext`, `keepLinesTogether`, `widowControl`), no
space between paragraphs of the same kind (`contextualSpacing`) and its writing direction (`direction`: ltr or rtl).
It can also set a border on each side (`borderTop`, `borderBottom`, `borderLeft`, `borderRight`: "solid 0.5pt
#000000" (solid, double, dotted or dashed, 0.25–12 pt, a colour) or "none"), and tab stops (`tabStops`: up to 30 of
"right 16cm dot" (alignment, position, leader), separated by ";").
The StyleSystem has a field for each (`indentRightCm`, `shading`, `keepWithNext`...), so a template or a Word style
can set them for a kind of block.

The engine writes them as CSS's own properties, and both exporters read them back:
- `margin-right`, `background-color`, `direction`;
- `break-after: avoid` (keep with next), `break-inside: avoid` (keep lines together);
- `widows`/`orphans` 2 or 1 (widow control on or off);
- `--contextual-spacing`;
- `border-top`/`-bottom`/`-left`/`-right`;
- `--tab-stops` (the browser ignores it; the Word export writes it back).

The editor draws shading, borders, indents and direction. Its pages don't follow the pagination controls yet, and
tab stops aren't shown there.

## Values (SEC-022)

A rule's value is written into CSS, into Word styles and into PDF styles as text.
`formatting/values.py::clean_rule_value` says what each property's value may be. It uses the StyleSystem's limits:
- fixed choices (alignment, orientation, page size);
- true/false switches;
- one safe font name;
- a renderable colour;
- numbers within bounds, in the units the renderers know;
- header and footer text, at most 500 characters.

It is applied everywhere a value can enter:
- the style and page-setting endpoints refuse anything else with 422;
- an instruction's rules and operations with such values are dropped (FMT-005);
- `validate_operations` refuses them;
- at resolve, a stored rule no renderer can use is skipped (`engine._usable`), so an old document can't carry one
  into a style either.

`tests/test_rule_values.py` pins this, and checks that every default and template rule passes unchanged.
