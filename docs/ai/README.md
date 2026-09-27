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

Operations are sorted by what they touch (`formatting/proposals.py`, AI-005):
- **format:** `set_style`;
- **structure:** `add_page_break`;
- **content:** `insert_element`, `delete_element`, `move_element`.

Formatting and structure apply at once, after the template and coarse rules. Before this, the formatting pass
silently dropped a style an instruction set on one element.

Content-changing operations are never applied from an instruction (brief §19: PLAN → VALIDATE → PREVIEW →
ACCEPT → APPLY). They are validated against the document, then stored as `Document.proposals`. Each proposal is a
`ProposedChange` (REV-001) with:
- type and category;
- the element, and where an insert or move goes;
- `before`: the text it would delete or move;
- `after`: the text it would add;
- the instruction that asked for it.

A proposal already waiting isn't added twice. The editor lists them under **Changes to review** in the
Instructions panel (AI-007):
- a deletion shows the block as it reads now, struck through;
- the status bar shows "N AI changes to review".

Accepting a proposal:
- `POST /documents/{id}/proposals/{proposal}/accept` validates it against the document as it is now, then applies
  it as one undoable step ("… (AI proposal accepted)" in the history);
- a proposal that no longer fits is refused with 409, never applied somewhere else.

Rejecting a proposal (`POST …/reject`) drops it, and the text stays as it is.

Proposals about blocks the user deleted, or blocks an accepted proposal removed, are dropped automatically.

## Tests

- `tests/test_ai_fidelity.py`: every alteration the brief names, in English and Bulgarian; the variants that aren't
  content; answers that never reach the document; per-piece fallback; logs without text.
- `tests/test_ai_proposals.py`: sorting, proposals with previews, accept as one undoable step, reject, stale
  proposals, no stacking, the per-element style regression.
- `frontend/editor/panels/ProposalsList.test.tsx`: the review list and the notice.
- `frontend/e2e/proposals.spec.ts`: instruct, review, accept, reload, reject, reload. The end-to-end server's AI is
  `backend/scripts/e2e_ai.py`. It answers two fixed instructions as the real model would; everything else behaves
  as if no AI key were set.
- `tests/test_ai_structure_analysis.py`, `tests/test_fidelity_report.py`.
