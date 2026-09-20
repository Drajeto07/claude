from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

from app.models.document import (
    Document,
    DocumentMetadata,
    Element,
    ElementType,
    InlineRun,
    ListItem,
    Mark,
    MarkType,
    Section,
    TableCell,
    TableContent,
    TableRow,
    plain_text_from_inline,
)

# "table" and "strikethrough" are built into markdown-it-py core but disabled
# under the "commonmark" preset by default -- .enable() turns them on without
# needing any extra plugin package.
_md = MarkdownIt("commonmark", {"html": False, "tasklists": True}).enable(["table", "strikethrough"])

_MARK_NODE_TYPES = {
    "strong": MarkType.BOLD,
    "em": MarkType.ITALIC,
    "s": MarkType.STRIKE,
}


def parse_markdown(text: str, title: str | None = None) -> Document:
    """Deterministic Markdown structure extraction. Every element gets
    confidence=1.0: this is a mechanical read of syntax the author explicitly
    wrote, not a probabilistic guess -- there is no AI involved on this path.
    """
    root = SyntaxTreeNode(_md.parse(text))

    section = Section(order=0)
    elements: list[Element] = []
    order = 0
    for node in root.children:
        element = _block_to_element(node, section.id, order)
        if element is not None:
            elements.append(element)
            order += 1

    derived_title = (
        elements[0].content if elements and elements[0].type == ElementType.HEADING else "Untitled Document"
    )
    return Document(
        metadata=DocumentMetadata(title=title or derived_title),
        sections=[section],
        elements=elements,
    )


def _block_to_element(node: SyntaxTreeNode, section_id: str, order: int) -> Element | None:
    if node.type == "heading":
        inline = _inline_runs(node)
        return Element(
            type=ElementType.HEADING,
            content=plain_text_from_inline(inline),
            inline=inline,
            parentId=section_id,
            order=order,
            level=int(node.tag[1]),
            confidence=1.0,
        )
    if node.type == "paragraph":
        inline = _inline_runs(node)
        return Element(
            type=ElementType.PARAGRAPH,
            content=plain_text_from_inline(inline),
            inline=inline,
            parentId=section_id,
            order=order,
            confidence=1.0,
        )
    if node.type in ("bullet_list", "ordered_list"):
        items = _list_items(node, level=0)
        content = "\n".join(plain_text_from_inline(item.inline) for item in items)
        return Element(
            type=ElementType.LIST,
            content=content,
            listItems=items,
            ordered=(node.type == "ordered_list"),
            parentId=section_id,
            order=order,
            confidence=1.0,
        )
    if node.type == "table":
        table = _table_content(node)
        content = "\n".join(
            " | ".join(plain_text_from_inline(cell.inline) for cell in row.cells) for row in table.rows
        )
        return Element(
            type=ElementType.TABLE,
            content=content,
            table=table,
            parentId=section_id,
            order=order,
            confidence=1.0,
        )
    if node.type == "blockquote":
        inline = _blockquote_inline(node)
        return Element(
            type=ElementType.QUOTE,
            content=plain_text_from_inline(inline),
            inline=inline,
            parentId=section_id,
            order=order,
            confidence=1.0,
        )
    if node.type == "fence":
        return Element(
            type=ElementType.CODE_BLOCK,
            content=node.content.rstrip("\n"),
            language=(node.info.strip() or None),
            parentId=section_id,
            order=order,
            confidence=1.0,
        )
    # "hr" (thematic break) carries no content -- skip. Anything else
    # unrecognized (raw html blocks, reference definitions) is skipped too.
    return None


def _inline_runs(node: SyntaxTreeNode) -> list[InlineRun]:
    inline_children = [child for child in node.children if child.type == "inline"]
    if not inline_children:
        return []
    return _walk_inline(inline_children[0].children, active_marks=[])


def _walk_inline(nodes: list[SyntaxTreeNode], active_marks: list[Mark]) -> list[InlineRun]:
    runs: list[InlineRun] = []
    for node in nodes:
        if node.type in ("text", "text_special"):
            if node.content:
                runs.append(InlineRun(text=node.content, marks=list(active_marks)))
        elif node.type == "softbreak":
            runs.append(InlineRun(text=" ", marks=list(active_marks)))
        elif node.type == "hardbreak":
            runs.append(InlineRun(text="\n", marks=list(active_marks)))
        elif node.type == "code_inline":
            runs.append(InlineRun(text=node.content, marks=[*active_marks, Mark(type=MarkType.CODE)]))
        elif node.type in _MARK_NODE_TYPES:
            runs.extend(_walk_inline(node.children, [*active_marks, Mark(type=_MARK_NODE_TYPES[node.type])]))
        elif node.type == "link":
            href = node.attrGet("href")
            link_mark = Mark(type=MarkType.LINK, href=str(href) if href is not None else None)
            runs.extend(_walk_inline(node.children, [*active_marks, link_mark]))
        # images and anything else inline-level are skipped this phase --
        # Markdown images are rare inside prose runs and not in scope here.
    return runs


def _list_items(node: SyntaxTreeNode, level: int) -> list[ListItem]:
    items: list[ListItem] = []
    for item_node in node.children:
        if item_node.type != "list_item":
            continue
        checked = item_node.meta.get("checked") if item_node.meta else None
        inline: list[InlineRun] = []
        nested_lists: list[SyntaxTreeNode] = []
        for child in item_node.children:
            if child.type == "paragraph":
                inline = _inline_runs(child)
            elif child.type == "inline":
                inline = _walk_inline(child.children, [])
            elif child.type in ("bullet_list", "ordered_list"):
                nested_lists.append(child)
        items.append(ListItem(inline=inline, level=level, checked=checked))
        for nested in nested_lists:
            items.extend(_list_items(nested, level=level + 1))
    return items


def _table_content(node: SyntaxTreeNode) -> TableContent:
    rows: list[TableRow] = []
    alignments: list[str | None] = []
    has_header_row = False

    for section_node in node.children:
        if section_node.type not in ("thead", "tbody"):
            continue
        for tr_node in section_node.children:
            if tr_node.type != "tr":
                continue
            cells: list[TableCell] = []
            for cell_index, cell_node in enumerate(tr_node.children):
                is_header = cell_node.type == "th"
                if is_header:
                    has_header_row = True
                inline = _inline_runs(cell_node) if any(c.type == "inline" for c in cell_node.children) else []
                if len(alignments) <= cell_index:
                    alignments.append(_cell_alignment(cell_node))
                cells.append(TableCell(inline=inline, header=is_header))
            rows.append(TableRow(cells=cells))

    return TableContent(rows=rows, hasHeaderRow=has_header_row, alignments=alignments or None)


def _cell_alignment(cell_node: SyntaxTreeNode) -> str | None:
    style = cell_node.attrs.get("style")
    if isinstance(style, str) and style.startswith("text-align:"):
        return style.split(":", 1)[1]
    return None


def _blockquote_inline(node: SyntaxTreeNode) -> list[InlineRun]:
    runs: list[InlineRun] = []
    for child in node.children:
        if child.type == "paragraph":
            if runs:
                runs.append(InlineRun(text="\n"))
            runs.extend(_inline_runs(child))
    return runs
