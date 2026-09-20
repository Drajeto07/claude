from app.models.document import ElementType
from app.parsers.plain_text import segment_plain_text


def test_first_short_line_becomes_heading():
    text = "Project Kickoff Notes\n\nThis document summarizes the key decisions made during the initial planning session.\n\nWe agreed to use a naive placeholder segmenter for Phase 1."

    document = segment_plain_text(text)

    assert len(document.elements) == 3

    heading = document.elements[0]
    assert heading.type == ElementType.HEADING
    assert heading.content == "Project Kickoff Notes"
    assert heading.level == 1
    assert heading.order == 0

    paragraph_one, paragraph_two = document.elements[1], document.elements[2]
    assert paragraph_one.type == ElementType.PARAGRAPH
    assert paragraph_one.level is None
    assert paragraph_one.order == 1
    assert paragraph_two.order == 2

    assert document.metadata.title == "Project Kickoff Notes"


def test_long_first_line_is_not_treated_as_heading():
    text = "This first paragraph is intentionally long enough that it should never be mistaken for a heading by the naive placeholder rule."

    document = segment_plain_text(text)

    assert len(document.elements) == 1
    assert document.elements[0].type == ElementType.PARAGRAPH
    assert document.metadata.title == "Untitled Document"


def test_blank_input_produces_no_elements():
    document = segment_plain_text("   \n\n   ")

    assert document.elements == []
