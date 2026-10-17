"""Tables drawn with ruling lines on a PDF's pages (tracker P2E-004): the lines and thin
rectangles the geometry read found (parsers/pdf_geometry.py), and the edges of outlined
rectangles, are ruling lines; lines that cross make a grid; the grid's columns and rows
are where its vertical and horizontal lines stand. A cell whose edge has no line along it
runs on into the next (a merged cell: colspan, rowspan). A filled rectangle under a cell
is its shading. The structure reconstruction (parsers/pdf_structure.py) puts each grid's
text into its cells and the table into the document where it stood.

Only grids with lines both ways are tables here: text merely set in columns, or ruled only
across, stays as text, a row a paragraph (reported)."""

from dataclasses import dataclass, field

from app.parsers.pdf_geometry import Box, PdfPage

# A line at most this thick is a ruling line, and at least RULE_LENGTH long.
RULE_THICKNESS = 2.5
RULE_LENGTH = 6.0
# Lines this close (points) are one; a line reaching this near another meets it.
SNAP = 2.0
# An edge is drawn when lines cover this share of it.
DRAWN = 0.8
# A filled rectangle covering this share of a cell shades it.
SHADES = 0.8
# Grids larger than this aren't read as tables (a form's boxes, a chart's grid).
MAX_ROWS, MAX_COLUMNS = 500, 40


@dataclass(frozen=True, slots=True)
class Rule:
    across: bool  # horizontal
    at: float  # its y (across) or x (down)
    start: float
    end: float


@dataclass(slots=True)
class GridCell:
    row: int
    column: int
    rowspan: int = 1
    colspan: int = 1
    shade: str | None = None  # "#rrggbb"


@dataclass(slots=True)
class Grid:
    xs: list[float]  # column edges, left to right
    ys: list[float]  # row edges, top to bottom
    cells: list[GridCell] = field(default_factory=list)  # the cells that start somewhere: covered ones left out
    spans: bool = False

    @property
    def box(self) -> Box:
        return (self.xs[0], self.ys[0], self.xs[-1], self.ys[-1])

    def rect(self, cell: GridCell) -> Box:
        return (self.xs[cell.column], self.ys[cell.row], self.xs[cell.column + cell.colspan], self.ys[cell.row + cell.rowspan])


def _rules(page: PdfPage) -> list[Rule]:
    rules: list[Rule] = []

    def add(x0: float, top: float, x1: float, bottom: float) -> None:
        if bottom - top <= RULE_THICKNESS and x1 - x0 >= RULE_LENGTH:
            rules.append(Rule(True, (top + bottom) / 2, x0, x1))
        elif x1 - x0 <= RULE_THICKNESS and bottom - top >= RULE_LENGTH:
            rules.append(Rule(False, (x0 + x1) / 2, top, bottom))

    for path in page.lines:
        add(*path.box)
    for path in page.rects:
        x0, top, x1, bottom = path.box
        if bottom - top <= RULE_THICKNESS or x1 - x0 <= RULE_THICKNESS:
            add(x0, top, x1, bottom)  # a filled strip drawn as a line
        elif path.stroke is not None:  # an outlined box: its four edges
            add(x0, top, x1, top)
            add(x0, bottom, x1, bottom)
            add(x0, top, x0, bottom)
            add(x1, top, x1, bottom)
    return rules


def _meets(a: Rule, b: Rule) -> bool:
    across, down = (a, b) if a.across else (b, a)
    return down.start - SNAP <= across.at <= down.end + SNAP and across.start - SNAP <= down.at <= across.end + SNAP


def _groups(rules: list[Rule]) -> list[list[Rule]]:
    """Rules that cross or touch, together (a union-find over the pairs that meet)."""
    parent = list(range(len(rules)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    across = [i for i, rule in enumerate(rules) if rule.across]
    down = [i for i, rule in enumerate(rules) if not rule.across]
    for i in across:
        for j in down:
            if _meets(rules[i], rules[j]):
                parent[root(i)] = root(j)
    groups: dict[int, list[Rule]] = {}
    for i, rule in enumerate(rules):
        groups.setdefault(root(i), []).append(rule)
    return list(groups.values())


def _edges(values: list[float]) -> list[float]:
    edges: list[float] = []
    for value in sorted(values):
        if edges and value - edges[-1] <= SNAP:
            continue
        edges.append(value)
    return edges


def _drawn(rules: list[Rule], across: bool, at: float, start: float, end: float) -> bool:
    """Whether lines run along this edge for most of its length."""
    covered = 0.0
    reach = start
    for rule in sorted((r for r in rules if r.across == across and abs(r.at - at) <= SNAP), key=lambda r: r.start):
        lo, hi = max(rule.start, reach), min(rule.end, end)
        if hi > lo:
            covered += hi - lo
            reach = hi
    return covered >= DRAWN * (end - start)


def _cells(grid: Grid, rules: list[Rule]) -> None:
    rows, columns = len(grid.ys) - 1, len(grid.xs) - 1
    taken = [[False] * columns for _ in range(rows)]
    for row in range(rows):
        for column in range(columns):
            if taken[row][column]:
                continue
            colspan = 1
            while column + colspan < columns and not taken[row][column + colspan] and not _drawn(
                rules, False, grid.xs[column + colspan], grid.ys[row], grid.ys[row + 1]
            ):
                colspan += 1
            rowspan = 1
            while row + rowspan < rows and not any(
                taken[row + rowspan][c] for c in range(column, column + colspan)
            ) and not _drawn(rules, True, grid.ys[row + rowspan], grid.xs[column], grid.xs[column + colspan]):
                rowspan += 1
            for r in range(row, row + rowspan):
                for c in range(column, column + colspan):
                    taken[r][c] = True
            grid.cells.append(GridCell(row, column, rowspan, colspan))
            grid.spans = grid.spans or rowspan > 1 or colspan > 1


def _shade(grid: Grid, page: PdfPage) -> None:
    fills = [path for path in page.rects if path.fill is not None and path.fill not in ("#ffffff",)]
    for cell in grid.cells:
        x0, top, x1, bottom = grid.rect(cell)
        area = (x1 - x0) * (bottom - top)
        for path in fills:
            px0, ptop, px1, pbottom = path.box
            overlap = max(0.0, min(x1, px1) - max(x0, px0)) * max(0.0, min(bottom, pbottom) - max(top, ptop))
            if area > 0 and overlap >= SHADES * area:
                cell.shade = path.fill


def find_grids(page: PdfPage) -> list[Grid]:
    """The ruled tables on an upright page, top to bottom. A turned page's are left as text."""
    if page.rotation:
        return []
    rules = _rules(page)
    grids = []
    for group in _groups(rules):
        across = [rule for rule in group if rule.across]
        down = [rule for rule in group if not rule.across]
        if len(across) < 2 or len(down) < 2:
            continue
        grid = Grid(xs=_edges([rule.at for rule in down]), ys=_edges([rule.at for rule in across]))
        rows, columns = len(grid.ys) - 1, len(grid.xs) - 1
        if rows < 1 or columns < 1 or rows * columns < 2 or rows > MAX_ROWS or columns > MAX_COLUMNS:
            continue
        _cells(grid, group)
        _shade(grid, page)
        grids.append(grid)
    return sorted(grids, key=lambda grid: (grid.ys[0], grid.xs[0]))
