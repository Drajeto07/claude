"""Blocks nested inside table cells, list items and quotes (tracker CORE-001):
the model holds them, validates them and gives every reader one way to see them."""

import pytest
from pydantic import ValidationError

from app.models.document import (
    MAX_BLOCK_DEPTH,
    Document,
    Element,
    ElementType,
    ImageContent,
    InlineRun,
    ListItem,
    ListNumbering,
    Mark,
    MarkType,
    TableCell,
    TableContent,
    TableRow,
    child_blocks,
    walk_elements,
)


def _paragraph(text: str, order: int = 0) -> Element:
    return Element(type=ElementType.PARAGRAPH, content=text, inline=[InlineRun(text=text)], order=order)


def _list(texts: list[str], *, ordered: bool = False, order: int = 0) -> Element:
    return Element(
        type=ElementType.LIST,
        content="\n".join(texts),
        listItems=[ListItem(inline=[InlineRun(text=text)]) for text in texts],
        ordered=ordered,
        order=order,
    )


def _table_with_cell_blocks(blocks: list[Element]) -> Element:
    cell = TableCell(inline=[InlineRun(text="\n".join(b.content for b in blocks))], blocks=blocks)
    return Element(type=ElementType.TABLE, content="", table=TableContent(rows=[TableRow(cells=[cell])]), order=0)


def test_a_cell_holds_a_list_code_and_a_picture_and_round_trips_through_json():
    blocks = [
        _list(["one", "two"], order=0),
        Element(type=ElementType.CODE_BLOCK, content="print(1)", language="python", order=1),
        Element(type=ElementType.IMAGE, content="", image=ImageContent(src="", assetId="a1", alt="Chart"), order=2),
    ]
    document = Document(elements=[_table_with_cell_blocks(blocks)])

    again = Document.model_validate_json(document.model_dump_json())

    assert again == document
    cell = again.elements[0].table.rows[0].cells[0]
    assert [block.type for block in cell.blocks] == [ElementType.LIST, ElementType.CODE_BLOCK, ElementType.IMAGE]
    assert cell.blocks[2].image.alt == "Chart"


def test_list_item_blocks_quote_children_and_numbering_round_trip():
    item = ListItem(
        inline=[InlineRun(text="Step one")],
        blocks=[Element(type=ElementType.CODE_BLOCK, content="make", order=0), _list(["a", "b"], ordered=True, order=1)],
    )
    steps = Element(
        type=ElementType.LIST,
        content="Step one",
        listItems=[item],
        ordered=True,
        numbering=ListNumbering(start=5, format="lowerRoman"),
        order=0,
    )
    quote = Element(type=ElementType.QUOTE, content="x\ny", children=[_paragraph("x"), _list(["y"], order=1)], order=1)
    document = Document(elements=[steps, quote])

    again = Document.model_validate_json(document.model_dump_json())

    assert again == document
    assert again.elements[0].numbering == ListNumbering(start=5, format="lowerRoman")
    assert again.elements[1].children[1].listItems[0].inline[0].text == "y"


def test_documents_without_nested_blocks_load_unchanged():
    legacy = {
        "elements": [
            {"type": "table", "content": "a", "order": 0, "table": {"rows": [{"cells": [{"inline": [{"text": "a"}]}]}]}},
            {"type": "list", "content": "b", "order": 1, "listItems": [{"inline": [{"text": "b"}], "level": 0}]},
        ]
    }
    document = Document.model_validate(legacy)
    assert document.elements[0].table.rows[0].cells[0].blocks is None
    assert document.elements[1].listItems[0].blocks is None
    assert document.elements[1].numbering is None and document.elements[0].children is None


def _nested(depth: int) -> Element:
    """A table whose single cell holds a table ... `depth` levels of nesting."""
    element = _paragraph("deepest")
    for _ in range(depth):
        element = _table_with_cell_blocks([element])
    return element


def test_nesting_is_capped():
    Document(elements=[_nested(MAX_BLOCK_DEPTH)])
    with pytest.raises(ValidationError, match="nest at most"):
        Element.model_validate(_nested(MAX_BLOCK_DEPTH + 1).model_dump())


@pytest.mark.parametrize("numbering", [{"start": -1}, {"start": 1_000_000}, {"format": "bullet"}, {"format": "(%1)"}])
def test_numbering_values_are_validated(numbering):
    with pytest.raises(ValidationError):
        ListNumbering.model_validate(numbering)


def test_walk_elements_sees_every_nested_block_in_reading_order():
    inner_table = _table_with_cell_blocks([_paragraph("in inner cell")])
    cell_list = _list(["cell item"])
    cell_list.listItems[0].blocks = [_paragraph("under the item")]
    outer = _table_with_cell_blocks([cell_list, inner_table])
    quote = Element(type=ElementType.QUOTE, content="", children=[_paragraph("quoted")], order=1)

    texts = [element.content for element in walk_elements([outer, quote]) if element.type == ElementType.PARAGRAPH]

    assert texts == ["under the item", "in inner cell", "quoted"]
    assert [child.type for child in child_blocks(outer)] == [ElementType.LIST, ElementType.TABLE]


def test_a_runs_marks_are_kept_in_one_order_whoever_wrote_them():
    """The editor lists marks its own way; the model keeps MarkType's order, so the
    same formatting is always the same data (EDIT-007: no save just for opening)."""
    run = InlineRun(
        text="a bold link",
        marks=[Mark(type=MarkType.TEXT_STYLE, color="#FF0000"), Mark(type=MarkType.LINK, href="https://example.com"), Mark(type=MarkType.BOLD)],
    )

    assert [mark.type for mark in run.marks] == [MarkType.BOLD, MarkType.LINK, MarkType.TEXT_STYLE]
