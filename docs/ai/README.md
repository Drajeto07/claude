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

## Prompt injection (AI-009)

A document is data, never instructions.

Every task fences the document in a tag named anew for each call (`ai/prompting.py::document_tag`, 8 random hex
digits). Its system rules carry `UNTRUSTED_DOCUMENT`: everything inside the tag is data, whatever it says. The
user's request stays outside the tag. A document can't close the fence, since it can't know the tag's name. The
call log records the task, tokens and outcome, never the text.

Whatever an answer says, steered by the document or simply wrong, only bounded and checked output gets through:
- **Structure analysis:** the text must come back exactly (`text_check`). The document type is a short slug,
  heading levels are 1–6, list levels 0–8, and a code block's language is a plain name
  (`ai/schemas.py`). A failing answer is retried, then the piece falls back.
- **Instructions:**
  - rule targets are kinds of blocks, properties are known ones, and values pass `formatting/values.py`;
  - operations name only listed elements;
  - inserted text is at most 10,000 characters, and inserting, deleting or moving text is only ever a proposal
    the user reviews.
- **Style analysis:** tone, summary and reasons are length-bounded, and flags naming unknown elements are dropped.
- **Heading labels (Format by Example):** only known ids and levels 1–6; an answer calling most paragraphs
  headings is ignored.

The Anthropic SDK moves the bounds the API doesn't take into the fields' descriptions, then validates the parsed
answer against the model locally. A failure is a ValidationError, which every AI step retries, then falls back
from.

## Budgets (AI-008)

Every job (an import, a formatting run, Format by Example) and every request that calls the AI gets an allowance:
- at most `AI_CALLS_PER_JOB` calls (default 50);
- all within `AI_SECONDS_PER_JOB` of the first call (default 900 s).

`ai/budget.py::BudgetedAIProvider` wraps the metered provider, both in `jobs/runner.py` and in
`api/deps.py::get_metered_ai_provider`. A call that would exceed the allowance is refused at once. A call still
running at the deadline is cancelled, and the job gets nothing more. In both cases the error is an
`AIBudgetExceededError`: a refusal, so every AI step takes its fallback.

Structure analysis doesn't retry after it. It splits the rest of the text into paragraphs and says so in the import
report ("The AI allowance for one document was used up…").

Other bounds:
- retries are capped in the settings (`AI_STRUCTURE_MAX_RETRIES` 0–3);
- each call's output is capped by its `max_tokens`, and its input by the piece size;
- so the calls bound a document's tokens too.

Before this, one long document could spend hours: 20 pieces × 2 attempts × 3 SDK tries × a 180 s timeout.

## Tests

- `tests/test_ai_fidelity.py`: every alteration the brief names, in English and Bulgarian; the variants that aren't
  content; answers that never reach the document; per-piece fallback; logs without text.
- `tests/test_ai_proposals.py`: sorting, proposals with previews, accept as one undoable step, reject, stale
  proposals, no stacking, the per-element style regression.
- `frontend/editor/panels/ProposalsList.test.tsx`: the review list and the notice.
- `frontend/e2e/proposals.spec.ts`: instruct, review, accept, reload, reject, reload. The end-to-end server's AI is
  `backend/scripts/e2e_ai.py`. It answers two fixed instructions as the real model would; everything else behaves
  as if no AI key were set.
- `tests/test_prompt_injection.py`: every task fences the document and says it is data; each fence is new; the
  document can't close it; out-of-bounds answers are refused and fall back; style-analysis output is bounded; an
  instruction steered by the document deletes nothing and styles nothing unchecked.
- `tests/test_ai_budget.py`: calls and deadline refused at once, a slow call cut off, bounded settings, a document
  finished without the AI once its allowance is spent, and a request's own allowance through the API.
- `tests/test_ai_structure_analysis.py`, `tests/test_fidelity_report.py`.

## Explaining Document Health (HLTH-003)

`app/ai/health_explanation.py`, `POST /api/v1/documents/{id}/health/explain` (`checkIds`, or every check that warns or
fails), the Health panel's "Explain" on each such check. The checks find what to fix and score the document,
deterministically (`formatting/health.py`); the AI only says in plain words why a finding matters and what to do.
- It is sent the failing checks -- id, title, summary, up to five issues each with a few words of up to three of their
  blocks (in the untrusted-document tag) -- never the score or the passing checks.
- Its rules forbid rating, scoring or grading anything, and adding findings of its own. An explanation that still
  rates ("scores", "40 out of 100", "grade") isn't shown; an answer that explains a check it wasn't asked about isn't
  used at all.
- Each call is metered as an AI operation and rate-limited with the other AI requests. Nothing is stored, and the
  document doesn't change. When the AI can't be used, the answer is `available: false` and the panel says so; the
  checks and their score stand as they are.
