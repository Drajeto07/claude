"""AI fidelity (brief §18, tracker AI-001..AI-004): an AI answer that should keep
the text as it is -- structure analysis only adds structure -- is compared with
the source token by token. Every alteration the brief names is caught and
classified; typographic variants and list or heading marks are not content; an
answer that changes the text never reaches the document, and the log says what
changed without the text."""

import asyncio
import logging

import pytest

from app.ai import structure_analysis
from app.ai.schemas import AIBlock, AIBlockType, AIStructureResponse
from app.ai.structure_analysis import analyze_structure
from app.fidelity.text_check import (
    DUPLICATE,
    NEGATION,
    NUMBER,
    PUNCTUATION,
    REORDERED,
    SENTENCE,
    UNIT,
    WORDS,
    changed_numbers,
    check_text,
)
from tests.fakes import FakeAIProvider

SOURCE = (
    "Dosage\n\n"
    "Take 5 mg twice a day with water. Do not exceed 20 mg in 24 hours. "
    "The trial on 2024-05-17 improved results by 12.5%."
)

# (name, altered text, the difference's category, a protected fact changed)
ALTERATIONS = [
    ("sentence deletion", SOURCE.replace(" Do not exceed 20 mg in 24 hours.", ""), NUMBER, True),
    ("word deletion", SOURCE.replace("twice a day with water", "twice a day"), WORDS, False),
    ("'not' removal", SOURCE.replace("Do not exceed", "Do exceed"), NEGATION, False),
    ("number change", SOURCE.replace("Take 5 mg", "Take 50 mg"), NUMBER, True),
    ("unit change", SOURCE.replace("Take 5 mg", "Take 5 g"), UNIT, True),
    ("percentage change", SOURCE.replace("12.5%", "125%"), NUMBER, True),
    ("decimal separator change", SOURCE.replace("12.5%", "12,5%"), NUMBER, True),
    ("date change", SOURCE.replace("2024-05-17", "2024-05-18"), NUMBER, True),
    ("added sentence", SOURCE + " Always consult your doctor first.", SENTENCE, False),
    (
        "reordered sentence",
        SOURCE.replace(
            "Take 5 mg twice a day with water. Do not exceed 20 mg in 24 hours.",
            "Do not exceed 20 mg in 24 hours. Take 5 mg twice a day with water.",
        ),
        REORDERED,
        False,
    ),
    ("duplicated content", SOURCE.replace("with water.", "with water. Take 5 mg twice a day with water."), DUPLICATE, True),
    ("punctuation alteration", SOURCE.replace("with water.", "with water?"), PUNCTUATION, False),
    ("heading change", SOURCE.replace("Dosage", "Dose"), WORDS, False),
]


@pytest.mark.parametrize(("name", "altered", "category", "protected"), ALTERATIONS, ids=[case[0] for case in ALTERATIONS])
def test_every_alteration_the_brief_names_is_caught_and_classified(name, altered, category, protected):
    check = check_text(SOURCE, altered)

    assert not check.verified
    assert [difference.category for difference in check.differences] == [category]
    assert check.protected is protected


def test_a_removed_negation_is_caught_in_bulgarian_too():
    check = check_text("Не приемайте повече от 20 мг.", "Приемайте повече от 20 мг.")

    assert [difference.category for difference in check.differences] == [NEGATION]


@pytest.mark.parametrize(
    "variant",
    [
        SOURCE.replace("\n\n", "\n").replace(". ", ".\n\n"),  # other line breaks and spacing
        SOURCE.replace("Dosage", "# Dosage"),  # a heading mark
        "Dosage\n\n" + "- Take 5 mg twice a day with water.\n- Do not exceed 20 mg in 24 hours.\n- The trial on 2024-05-17 improved results by 12.5%.",
        "Dosage\n\n1. Take 5 mg twice a day with water.\n2. Do not exceed 20 mg in 24 hours.\n3. The trial on 2024–05–17 improved results by 12.5%.",
    ],
)
def test_structure_and_typography_are_not_content(variant):
    assert check_text(SOURCE, variant).verified


def test_quotes_dashes_and_ellipsis_in_any_style_are_the_same_text():
    assert check_text('He said "wait..." - then left', "He said “wait…” — then left").verified
    assert check_text("а) първо\nб) второ", "първо\nвторо").verified  # Cyrillic list letters


def _answer(*texts: str) -> AIStructureResponse:
    return AIStructureResponse(
        document_type="general",
        document_type_confidence=0.9,
        blocks=[AIBlock(type=AIBlockType.PARAGRAPH, text=text, confidence=0.9) for text in texts],
    )


@pytest.mark.parametrize(("name", "altered"), [(case[0], case[1]) for case in ALTERATIONS], ids=[case[0] for case in ALTERATIONS])
def test_an_answer_that_alters_the_text_never_reaches_the_document(name, altered):
    provider = FakeAIProvider([_answer(altered), _answer(altered)])

    document = asyncio.run(analyze_structure(provider, SOURCE))

    assert provider.calls == 2  # the answer and the retry, both refused
    assert all(element.confidence is None for element in document.elements)  # split into paragraphs instead
    assert check_text(SOURCE, "\n\n".join(element.content for element in document.elements)).verified


def test_an_answer_that_only_adds_structure_is_used():
    answer = AIStructureResponse(
        document_type="general",
        document_type_confidence=0.9,
        blocks=[
            AIBlock(type=AIBlockType.HEADING, text="Dosage", level=1, confidence=0.9),
            AIBlock(type=AIBlockType.PARAGRAPH, text="Take 5 mg twice a day with water. Do not exceed 20 mg in 24 hours.", confidence=0.9),
            AIBlock(type=AIBlockType.PARAGRAPH, text="The trial on 2024–05–17 improved results by 12.5%.", confidence=0.8),
        ],
    )
    provider = FakeAIProvider([answer])

    document = asyncio.run(analyze_structure(provider, SOURCE))

    assert provider.calls == 1
    assert [element.type.value for element in document.elements] == ["heading", "paragraph", "paragraph"]


def test_the_log_says_what_changed_never_the_text(caplog):
    altered = SOURCE.replace("Do not exceed", "Do exceed")
    provider = FakeAIProvider([_answer(altered), _answer(altered)])

    with caplog.at_level(logging.WARNING, logger="app.ai.structure_analysis"):
        asyncio.run(analyze_structure(provider, SOURCE))

    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "negation x1" in logged
    for word in ("exceed", "Dosage", "water", "mg"):
        assert word not in logged


def test_numbers_are_facts_even_where_the_words_may_change():
    # A translation may change every word; its amounts, dates and identifiers may not change.
    assert changed_numbers("Take 5 mg by 2024-05-17 (COVID-19 protocol).", "Приемайте 5 мг до 2024-05-17 (протокол COVID-19).") == ([], [])
    assert changed_numbers("Take 5 mg twice, 12.5% less.", "Приемайте 50 мг два пъти, 12,5% по-малко.") == (["12.5%", "5"], ["12,5%", "50"])


def test_a_piece_that_alters_the_text_falls_back_alone(monkeypatch):
    monkeypatch.setattr(structure_analysis, "CHUNK_CHARS", 70)  # the heading and its paragraph, then the second part
    first = "Introduction\n\nThis first part is kept exactly as it was written."
    second = "The second part says the dose is 5 mg and never more."
    text = f"{first}\n\n{second}"
    assert len(structure_analysis.split_into_chunks(text)) == 2
    kept = AIStructureResponse(
        document_type="general",
        document_type_confidence=0.9,
        blocks=[
            AIBlock(type=AIBlockType.HEADING, text="Introduction", level=1, confidence=0.9),
            AIBlock(type=AIBlockType.PARAGRAPH, text="This first part is kept exactly as it was written.", confidence=0.9),
        ],
    )
    altered = _answer(second.replace("5 mg", "50 mg"))
    provider = FakeAIProvider([kept, altered, altered])

    document = asyncio.run(analyze_structure(provider, text))

    assert provider.calls == 3
    assert [(element.type.value, element.confidence) for element in document.elements] == [
        ("heading", 0.9),
        ("paragraph", 0.9),
        ("paragraph", None),  # only this piece was split without the AI
    ]
    assert document.elements[-1].content == second
