"""A template's structure applied to a document (tracker FMT-001): what a StyleSystem says about
tables, lists and heading numbering, set on the document's own tables, lists and headings --
things a formatting rule can't carry. Only what the template sets changes; nothing is applied
from a template that sets none of it."""

from app.formatting.style_system import StructureStyle
from app.models.document import Document, ElementType, ListNumbering, TableBorders, walk_elements


def applies(structure: StructureStyle) -> bool:
    tables, lists = structure.tables, structure.lists
    return any(
        value is not None
        for value in (tables.border, tables.headerShading, tables.headerBold, lists.bulletLevels, lists.numberedLevels, structure.headingNumbering)
    )


def apply_structure(document: Document, structure: StructureStyle) -> int:
    """Sets the structure on the document; returns how many tables and lists it changed."""
    changed = 0
    tables, lists = structure.tables, structure.lists
    for element in walk_elements(document.elements):
        if element.type == ElementType.TABLE and element.table is not None:
            table = element.table
            if tables.border is not None:
                border = tables.border
                table.borders = TableBorders(top=border, bottom=border, left=border, right=border, insideH=border, insideV=border)
            if tables.headerBold is not None:
                table.headerBold = tables.headerBold
            if tables.headerShading is not None and table.hasHeaderRow and table.rows:
                for cell in table.rows[0].cells:
                    cell.background = tables.headerShading
            changed += any(value is not None for value in (tables.border, tables.headerBold, tables.headerShading))
        elif element.type == ElementType.LIST:
            levels = lists.numberedLevels if element.ordered else lists.bulletLevels
            if levels:
                start = element.numbering.start if element.numbering else 1
                first = levels[0].format
                fmt = first if element.ordered and first not in ("bullet", "none") else "decimal"
                element.numbering = ListNumbering(start=start, format=fmt, levels=[level.model_copy() for level in levels])
                changed += 1
    if structure.headingNumbering is not None:
        document.headingNumbering = structure.headingNumbering.model_copy(update={"sourceNumId": None})
    return changed
