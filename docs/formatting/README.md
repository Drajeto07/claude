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
  pasted picture's width. `PUT /documents/{id}/content` carries these as `styles` (`DirectStyle`). They are stored
  as the element's own live override, without a revision entry, because they belong to the typing saved with them.
  A block split off one keeps its alignment, as in Word.

## Paragraph properties (DOCX-014)

Besides fonts, alignment, spacing and indents, a rule can set a paragraph's right indent (`indentRight`), its
background colour (`shading`), Word's pagination controls (`keepWithNext`, `keepLinesTogether`, `widowControl`), no
space between paragraphs of the same kind (`contextualSpacing`) and its writing direction (`direction`: ltr or rtl).
The StyleSystem has a field for each (`indentRightCm`, `shading`, `keepWithNext`...), so a template or a Word style
can set them for a kind of block.

The engine writes them as CSS's own properties, and both exporters read them back:
- `margin-right`, `background-color`, `direction`;
- `break-after: avoid` (keep with next), `break-inside: avoid` (keep lines together);
- `widows`/`orphans` 2 or 1 (widow control on or off);
- `--contextual-spacing`.

The editor draws shading, indents and direction. Its pages don't follow the pagination controls yet.

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
