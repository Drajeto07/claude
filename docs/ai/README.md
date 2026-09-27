# AI in SmartDoc

The AI finds structure, reads formatting instructions, labels a reference document's styles and explains health
checks. It never writes styles directly: it returns structured, validated output, and the deterministic formatting
engine applies it. It never changes a document's words on its own (brief §18–19).

Providers sit behind `app/ai/base.py::AIProvider`; the Anthropic one is `anthropic_provider.py`. Tests use
`tests/fakes.py::FakeAIProvider`. Document text always goes to the model inside an untrusted-document tag
(`ai/prompting.py`).

## Structure analysis (pasted prose)

`ai/structure_analysis.py` handles text that doesn't look like Markdown. It goes to the AI in pieces of about 8,000
characters, split between paragraphs. Each piece is told the headings found before it.

**The fidelity check (AI-001..AI-004).** An answer must hold its piece's text exactly: every word, number and
punctuation mark, in order, with nothing left out, added or repeated. `app/fidelity/text_check.py::check_text`
compares them token by token. Numbers keep their sign, decimals, separators and percent sign.

Not content, and ignored by the check:
- spacing and line breaks;
- typographic variants: quote styles, dash kinds, `…` vs `...`;
- table cell separators;
- list and heading marks at the start of a line (`•`, `-`, `1.`, `а)`, `#`), which become structure.

Each difference is classified: a number, unit, negation, whole sentence, duplicate, reordering, punctuation, or
other words. Numbers and units are *protected facts* (AI-002).

An answer that fails is retried once with a reminder. If it fails again, that piece alone is split into paragraphs
by rules (`parsers/plain_text.py`), so its text is kept as it was. The log says what changed ("negation x1") and
never the text itself.

The import then checks every word of the text against the document again (`docs/architecture/fidelity.md`).

**Facts where words may rightly change.** `text_check.changed_numbers(source, result)` names the numbers a result
lost or gained: amounts, percentages, dates and identifiers with digits. It is for translation and for rewording
the user asked for, where every word may differ but 5 mg may never become 50 mg.

## Formatting instructions

`ai/instruction_extraction.py` turns an instruction ("make headings blue, 14 pt") into two things:
- **Coarse rules**, targeted at kinds of blocks. Their values are checked by `formatting/values.py`, and unusable
  ones are dropped.
- **Operations**: `set_style` on one element, `insert_element`, `delete_element`, `move_element` and
  `add_page_break`.

Operations that change content are high-risk (brief §19). Tasks AI-005..AI-007 and REV-001 make them proposals
the user reviews before anything is applied.

## Tests

- `tests/test_ai_fidelity.py`: every alteration the brief names, in English and Bulgarian; the variants that aren't
  content; answers that never reach the document; per-piece fallback; logs without text.
- `tests/test_ai_structure_analysis.py`, `tests/test_fidelity_report.py`.
