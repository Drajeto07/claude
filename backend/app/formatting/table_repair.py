"""Broken tables (tracker REV-004, brief §60): a table whose rows don't fill its grid -- a row
short of the others' width (its cells end early), a cell spanning down past the last row -- or
with rows holding nothing at all. Found as a Document Health check (health.py `broken_tables`)
and put right as a proposed fix to review (health_fixes.py): a short row gets empty cells to the
table's width, a span past the last row ends at it, an empty row goes (never the table's last).
A row may be short only where cells spanning down from above fill it, as Word draws merges."""

from dataclasses import dataclass, field

from app.models.document import Element, ElementType, TableCell, TableContent, plain_text_from_inline


@dataclass
class TableProblems:
    width: int
    short: list[int] = field(default_factory=list)  # rows whose cells end before the table's width
    overflowing: list[int] = field(default_factory=list)  # rows with a cell spanning past the last row
    empty: list[int] = field(default_factory=list)  # rows holding nothing

    def __bool__(self) -> bool:
        return bool(self.short or self.overflowing or self.empty)


def _occupied(table: TableContent) -> list[set[int]]:
    """The grid columns each row's cells -- its own, and those spanning down into it -- cover."""
    covered: list[set[int]] = [set() for _ in table.rows]
    for row_index, row in enumerate(table.rows):
        column = 0
        for cell in row.cells:
            while column in covered[row_index]:
                column += 1
            for down in range(cell.rowspan):
                if row_index + down < len(covered):
                    covered[row_index + down].update(range(column, column + cell.colspan))
            column += cell.colspan
    return covered


def _empty(cell: TableCell) -> bool:
    return not plain_text_from_inline(cell.inline).strip() and not cell.blocks


def table_problems(table: TableContent) -> TableProblems:
    covered = _occupied(table)
    width = max((max(columns) + 1 for columns in covered if columns), default=0)
    problems = TableProblems(width=width)
    for row_index, row in enumerate(table.rows):
        if len(covered[row_index]) < width:
            problems.short.append(row_index)
        if any(row_index + cell.rowspan > len(table.rows) for cell in row.cells):
            problems.overflowing.append(row_index)
        spanned_into = len(covered[row_index]) > sum(cell.colspan for cell in row.cells)  # merged down into from above
        if row.cells and all(_empty(cell) for cell in row.cells) and not spanned_into and all(cell.rowspan == 1 for cell in row.cells):
            problems.empty.append(row_index)
    if len(problems.empty) == len(table.rows):  # a table of nothing but empty rows keeps them: it isn't broken, only blank
        problems.empty = []
    return problems


def repaired(element: Element) -> Element | None:
    """The table put right, or None when nothing in it is broken."""
    if element.type != ElementType.TABLE or element.table is None:
        return None
    problems = table_problems(element.table)
    if not problems:
        return None
    table = element.table.model_copy(deep=True)
    rows = len(table.rows)
    for row_index, row in enumerate(table.rows):
        for cell in row.cells:
            cell.rowspan = min(cell.rowspan, rows - row_index)
    covered = _occupied(table)
    for row_index in problems.short:
        missing = problems.width - len(covered[row_index])
        header = bool(table.rows[row_index].cells and table.rows[row_index].cells[0].header)
        table.rows[row_index].cells.extend(TableCell(inline=[], header=header) for _ in range(missing))
    table.rows = [row for row_index, row in enumerate(table.rows) if row_index not in set(problems.empty)]
    fixed = element.model_copy(deep=True, update={"table": table})
    fixed.content = "\n".join(" | ".join(plain_text_from_inline(cell.inline) for cell in row.cells) for row in table.rows)
    return fixed


def describe(problems: TableProblems) -> list[str]:
    said = []
    if problems.short:
        said.append(f"{len(problems.short)} row{'s' if len(problems.short) != 1 else ''} short of the table's {problems.width} columns")
    if problems.overflowing:
        said.append("a cell merged down past the last row")
    if problems.empty:
        said.append(f"{len(problems.empty)} empty row{'s' if len(problems.empty) != 1 else ''}")
    return said

