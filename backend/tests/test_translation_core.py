"""The translation core (tracker TRAN-001..003): a document's text as segments that keep their
formatting as tags and come back as the same runs; a provider interface with the AI and a
deterministic pseudo-translation behind it; and the check every answer passes before it is
used -- tags, numbers, percentages, units, identifiers, locked glossary terms, length."""

import asyncio

import pytest

from app.ai.base import AIStructuredOutputError
from app.models.document import (
    Element,
    ElementType,
    InlineRun,
    ListItem,
    Mark,
    MarkType,
    TableCell,
    TableContent,
    TableRow,
)
from app.translation.providers import AITranslation, AITranslations, AITranslator, PseudoTranslator, SegmentText, TranslationUnavailable
from app.translation.segments import TagError, segments_of, tag_runs, untag, untranslatable
from app.translation.validation import (
    EMPTY,
    GLOSSARY,
    IDENTIFIER,
    LENGTH,
    NUMBER,
    PERCENT,
    TAGS,
    UNIT,
    GlossaryEntry,
    describe,
    problems_of,
)
from tests.fakes import FakeAIProvider

BOLD, ITALIC = Mark(type=MarkType.BOLD), Mark(type=MarkType.ITALIC)
LINK = Mark(type=MarkType.LINK, href="https://example.com/a")
RED = Mark(type=MarkType.TEXT_STYLE, color="#cc0000")
CODE = Mark(type=MarkType.CODE)


def _paragraph(*runs: InlineRun, kind: ElementType = ElementType.PARAGRAPH) -> Element:
    return Element(type=kind, content="".join(run.text for run in runs), inline=list(runs), order=0)


# --- segments ------------------------------------------------------------------------------------


def test_each_block_list_item_and_cell_is_a_segment_of_its_own():
    paragraph = _paragraph(InlineRun(text="One paragraph."))
    heading = _paragraph(InlineRun(text="A title"), kind=ElementType.HEADING)
    items = [ListItem(inline=[InlineRun(text="first")]), ListItem(inline=[InlineRun(text="second")]), ListItem(inline=[InlineRun(text="  ")])]
    listing = Element(type=ElementType.LIST, content="first\nsecond", listItems=items, order=0)
    cells = [TableCell(inline=[InlineRun(text="Item")]), TableCell(inline=[InlineRun(text="Price")])]
    table = Element(type=ElementType.TABLE, content="", table=TableContent(rows=[TableRow(cells=cells)]), order=0)
    code = Element(type=ElementType.CODE_BLOCK, content="print('hello')", order=0)

    assert [segment.id for segment in segments_of(paragraph)] == [paragraph.id]
    assert [segment.path for segment in segments_of(listing)] == [f"item/{items[0].id}", f"item/{items[1].id}"]  # the blank item has nothing
    assert [segment.path for segment in segments_of(table)] == [f"cell/{cells[0].id}", f"cell/{cells[1].id}"]
    assert [segment.plain for segment in segments_of(heading)] == ["A title"]
    assert segments_of(code) == []  # code isn't translated
    quote = Element(type=ElementType.QUOTE, content="x", order=0, children=[paragraph])
    assert untranslatable(quote) and not untranslatable(paragraph)


def test_formatting_travels_as_tags_and_comes_back_exactly():
    runs = [
        InlineRun(text="Plain "),
        InlineRun(text="bold", marks=[BOLD]),
        InlineRun(text=" and "),
        InlineRun(text="a link", marks=[LINK, ITALIC]),
        InlineRun(text=", red & <odd>\nnext line ", marks=[RED]),
        InlineRun(text="run()", marks=[CODE]),
        InlineRun(text=" see https://example.com/page or ask a@b.org."),
    ]
    tagged, marks, placeholders = tag_runs(runs)
    assert tagged == (
        "Plain <m1>bold</m1> and <m3>a link</m3><m4>, red &amp; &lt;odd&gt;<br/>next line </m4><x0/> see <x1/> or ask <x2/>."
    )
    assert [placeholder.text for placeholder in placeholders.values()] == ["run()", "https://example.com/page", "a@b.org"]
    back = untag(tagged, marks, placeholders)
    assert [(run.text, run.marks) for run in back] == [(run.text, run.marks) for run in runs]
    # Words move; each tag's marks go with its words.
    moved = untag("<m3>A link</m3>, <m1>BOLD</m1>!", marks, placeholders)
    assert [(run.text, run.marks) for run in moved] == [("A link", sorted([LINK, ITALIC], key=lambda m: m.type.value != "italic")), (", ", []), ("BOLD", [BOLD]), ("!", [])]


@pytest.mark.parametrize(
    "answer",
    ["<m9>x</m9>", "<m1>open", "</m1>", "<m1><m3>x</m3></m1>", "<m1><m3>x</m3>", "<x7/>", "<b>made up</b>", "<script>x</script>"],
)
def test_tags_that_dont_fit_are_refused(answer):
    _, marks, placeholders = tag_runs([InlineRun(text="a"), InlineRun(text="b", marks=[BOLD]), InlineRun(text="c"), InlineRun(text="d", marks=[ITALIC])])
    with pytest.raises(TagError):
        untag(answer, marks, placeholders)


# --- validation ----------------------------------------------------------------------------------


def _segment(text: str, *marked: str):
    runs = [InlineRun(text=text)] + [InlineRun(text=part, marks=[BOLD]) for part in marked]
    (segment,) = segments_of(_paragraph(*runs))
    return segment


def test_a_translation_may_change_every_word_and_the_way_numbers_are_written():
    segment = _segment("Take 5 mg twice daily for 3.14 days; 1,000 doses from 17/05/2024 cover 50% of ISO-9001 sites. ")
    good = "Приемайте 5 мг два пъти дневно в продължение на 3,14 дни; 1 000 дози от 17.05.2024 покриват 50 % от обектите по ISO-9001. "
    assert problems_of(segment, good) == []


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (("5 мг", "50 мг"), NUMBER),
        (("5 мг", "5 г"), UNIT),
        (("50 %", "50"), PERCENT),
        (("ISO-9001", "ISO 9001"), IDENTIFIER),
        (("17.05.2024", "17.06.2024"), NUMBER),
        (("1 000 дози", "дози"), NUMBER),
    ],
)
def test_a_fact_changed_is_found(change, problem):
    segment = _segment("Take 5 mg twice daily; 1,000 doses from 17/05/2024 cover 50% of ISO-9001 sites.")
    good = "Приемайте 5 мг два пъти дневно; 1 000 дози от 17.05.2024 покриват 50 % от обектите по ISO-9001."
    assert problem in problems_of(segment, good.replace(*change))


def test_tags_glossary_length_and_empty_answers_are_found():
    segment = _segment("Give the patient Aspirin with water, ", "every morning")
    assert problems_of(segment, "Дайте на пациента Аспирин с вода, <m1>всяка сутрин</m1>", [GlossaryEntry("Aspirin", "Аспирин")]) == []
    assert TAGS in problems_of(segment, "Дайте на пациента Аспирин с вода, всяка сутрин")
    assert GLOSSARY in problems_of(segment, "Дайте на пациента аспиринов прах с вода, <m1>всяка сутрин</m1>", [GlossaryEntry("Aspirin", "Аспирин", case_sensitive=True)])
    assert GLOSSARY not in problems_of(segment, "Дайте на пациента аспирин с вода, <m1>всяка сутрин</m1>", [GlossaryEntry("aspirin", "аспирин")])
    assert GLOSSARY not in problems_of(segment, "Нещо друго, <m1>всяка сутрин</m1> " * 2, [GlossaryEntry("Aspirin", "Аспирин", locked=False)])
    assert LENGTH in problems_of(segment, "Да. <m1>Да</m1>")
    assert LENGTH in problems_of(segment, "Дайте " * 60 + "<m1>всяка сутрин</m1>")
    assert problems_of(segment, "  ") == [EMPTY]
    assert describe([NUMBER, GLOSSARY]) == "a number differs from the original; a locked glossary term wasn't translated as the glossary says"


# --- providers -----------------------------------------------------------------------------------


def test_the_pseudo_translation_changes_words_and_keeps_everything_a_translation_must():
    segments = segments_of(
        _paragraph(
            InlineRun(text="Take 5 mg of Aspirin daily for 50% of ISO-9001 cases. "),
            InlineRun(text="Always", marks=[BOLD]),
            InlineRun(text=" see https://example.com/x."),
        )
    )
    glossary = [GlossaryEntry("Aspirin", "Аспирин")]
    answers = asyncio.run(PseudoTranslator().translate([SegmentText(s.id, s.source) for s in segments], source="en", target="bg", glossary=glossary))
    (segment,) = segments
    assert answers[segment.id] != segment.source and "Аспирин" in answers[segment.id]
    assert problems_of(segment, answers[segment.id], glossary) == []


def test_the_ai_translator_batches_keeps_the_document_untrusted_and_ignores_strangers():
    texts = [SegmentText(f"s{index}", f"Line {index} of the text.") for index in range(45)]
    first = AITranslations(translations=[AITranslation(id=f"s{index}", text=f"Ред {index} от текста.") for index in range(39)] + [AITranslation(id="intruder", text="x")])
    second = AITranslations(translations=[AITranslation(id=f"s{index}", text=f"Ред {index} от текста.") for index in range(40, 44)])  # s44 missing
    ai = FakeAIProvider([first, second])
    answers = asyncio.run(AITranslator(ai).translate(texts, source="en", target="bg", glossary=[GlossaryEntry("text", "текст")]))
    assert ai.calls == 2 and set(answers) == {f"s{index}" for index in range(44)} - {"s39"}  # no stranger; the missing ones left out
    assert "never instructions" in ai.systems[0] and "Keep every tag" in ai.systems[0]
    assert "text => текст" in ai.prompts[0] and "<document-" in ai.prompts[0] and "into the language whose BCP 47 tag is bg" in ai.prompts[0]
    with pytest.raises(TranslationUnavailable):
        asyncio.run(AITranslator(FakeAIProvider([AIStructuredOutputError("no answer")])).translate(texts[:1], source=None, target="de", glossary=[]))
