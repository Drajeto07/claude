import { assetUrl } from "@/services/api";
import type { Document, Element, ElementType, InlineRun, ListItem, Mark, NumberFormat, TableContent } from "@/types/document";

import { cssFontStack } from "./fontStack";

type TiptapNode = Record<string, unknown>;
type ResolvedStyles = Document["resolvedStyles"];

const _ELEMENT_TYPE_TO_TARGET: Partial<Record<ElementType, string>> = {
  list: "List",
  table: "Table",
  quote: "Quote",
  caption: "Caption",
  footnote: "Footnote",
  code_block: "CodeBlock",
  image: "Image",
  page_break: "PageBreak",
  section_break: "SectionBreak",
  horizontal_rule: "HorizontalRule",
};

// Ported 1:1 from the backend's target_for_element (app/models/document.py) --
// must stay in lockstep, since this is the join key into resolvedStyles.
export function targetForElement(el: Element): string {
  if (el.type === "heading") return `Heading ${el.level ?? 1}`;
  return _ELEMENT_TYPE_TO_TARGET[el.type] ?? "Paragraph";
}

/** The block's `style` attribute: its resolved style (its own, or its kind's) as CSS. */
export function appliedStyle(el: Element, resolvedStyles: ResolvedStyles): string | null {
  const css = resolvedStyles[el.styleRef ?? targetForElement(el)];
  if (!css || Object.keys(css).length === 0) return null;
  return Object.entries(css)
    .filter(([property]) => !property.startsWith("--")) // data such as --line-spacing, not display
    .map(([property, value]) => `${property}:${property === "font-family" ? cssFontStack(value) : value}`)
    .join(";");
}

function styleAttrFor(el: Element, resolvedStyles: ResolvedStyles): TiptapNode {
  const style = appliedStyle(el, resolvedStyles);
  return style ? { style } : {};
}

/** A paragraph's or heading's own alignment -- one its kind doesn't give it -- as the
 * editor's textAlign, so a block split off it keeps it, as in Word
 * (tiptapToDocument.ts saves it for the new block). */
function ownAlignment(el: Element, resolvedStyles: ResolvedStyles): TiptapNode {
  if (!el.styleRef || el.styleRef !== el.id) return {};
  const own = resolvedStyles[el.id]?.["text-align"];
  return own && own !== resolvedStyles[targetForElement(el)]?.["text-align"] ? { textAlign: own } : {};
}

export function documentToTiptapJSON(doc: Document): TiptapNode {
  const sorted = [...doc.elements].sort((a, b) => a.order - b.order);
  return { type: "doc", content: sorted.map((el) => elementToNode(el, doc.resolvedStyles)) };
}

// `nested`: a block inside a table cell, a list item or a quote. Those carry no
// element id or look of their own in the editor; they save back by position.
function elementToNode(el: Element, resolvedStyles: ResolvedStyles, nested = false): TiptapNode {
  const confidenceAttrs = el.confidence !== null ? { confidence: el.confidence } : {};
  const nodeAttrs: TiptapNode = nested ? {} : { elementId: el.id, ...confidenceAttrs, ...styleAttrFor(el, resolvedStyles) };

  switch (el.type) {
    case "heading":
      return {
        type: "heading",
        attrs: { level: el.level ?? 1, ...nodeAttrs, ...(nested ? {} : ownAlignment(el, resolvedStyles)) },
        content: inlineToTiptap(el.inline, el.content),
      };
    case "list":
      return listElementToNode(el, nodeAttrs, resolvedStyles);
    case "table":
      return tableElementToNode(el, nodeAttrs, resolvedStyles);
    case "image":
      return el.image
        ? {
            type: "image",
            attrs: {
              src: el.image.assetId ? assetUrl(el.image.assetId) : el.image.src,
              alt: el.image.alt ?? undefined,
              title: el.image.title ?? undefined,
              ...nodeAttrs,
            },
          }
        : paragraphNode(el, nodeAttrs);
    case "code_block":
      return {
        type: "codeBlock",
        attrs: { language: el.language ?? null, ...nodeAttrs },
        content: el.content ? [{ type: "text", text: el.content }] : [],
      };
    case "quote":
      return {
        type: "blockquote",
        attrs: nodeAttrs,
        content: el.children?.length
          ? el.children.map((child) => elementToNode(child, resolvedStyles, true))
          : [{ type: "paragraph", content: inlineToTiptap(el.inline, el.content) }],
      };
    case "page_break":
      return { type: "pageBreak", attrs: nodeAttrs };
    case "section_break":
      return { type: "sectionBreak", attrs: { ...nodeAttrs, section: el.sectionBreak ?? null } };
    case "horizontal_rule":
      return { type: "horizontalRule", attrs: nodeAttrs };
    case "caption":
    case "footnote":
      // Nodes of their own (caption.ts, footnote.ts), so they save back as what they are.
      return {
        type: el.type,
        attrs: nodeAttrs,
        content: inlineToTiptap(el.inline, el.content),
      };
    // paragraph/other: "other" (a block the AI couldn't classify) has no node of
    // its own and is edited, and saved, as a paragraph.
    default:
      return paragraphNode(el, nested ? nodeAttrs : { ...nodeAttrs, ...ownAlignment(el, resolvedStyles) });
  }
}

function paragraphNode(el: Element, nodeAttrs: TiptapNode): TiptapNode {
  return {
    type: "paragraph",
    attrs: nodeAttrs,
    content: inlineToTiptap(el.inline, el.content),
  };
}

function listElementToNode(el: Element, nodeAttrs: TiptapNode, resolvedStyles: ResolvedStyles): TiptapNode {
  const items = el.listItems ?? [];
  // Any item with a checkbox makes it a checklist (the rest get empty boxes), so
  // no checked state is ever lost on the way through the editor.
  const kind = items.some((item) => item.checked !== null) ? "task" : el.ordered ? "ordered" : "bullet";
  const numbering = kind === "ordered" && el.numbering ? { start: el.numbering.start, type: HTML_LIST_TYPE[el.numbering.format] } : {};
  return {
    type: LIST_NODE[kind],
    attrs: { ...nodeAttrs, ...numbering },
    content: buildNestedListItems(items, 0, kind, resolvedStyles),
  };
}

type ListKind = "bullet" | "ordered" | "task";
const LIST_NODE: Record<ListKind, string> = { bullet: "bulletList", ordered: "orderedList", task: "taskList" };
// The ordered list's `type` attribute (HTML's <ol type>) for each numbering format.
const HTML_LIST_TYPE: Record<NumberFormat, string | null> = { decimal: null, lowerLetter: "a", upperLetter: "A", lowerRoman: "i", upperRoman: "I" };

// Groups a flat [{level:0}, {level:1}, {level:1}, {level:0}, ...] array into
// a nested Tiptap listItem tree -- the backend flattens nesting depth into
// ListItem.level rather than a recursive structure (see Document Model
// design notes), so this is the inverse projection back into a real tree.
function buildNestedListItems(items: ListItem[], level: number, kind: ListKind, resolvedStyles: ResolvedStyles): TiptapNode[] {
  const nodes: TiptapNode[] = [];
  let index = 0;
  while (index < items.length) {
    const item = items[index];
    if (item.level < level) break;
    index += 1;

    const nestedStart = index;
    while (index < items.length && items[index].level > level) {
      index += 1;
    }
    // The item's first paragraph, whatever else it holds, then its deeper levels.
    const children: TiptapNode[] = [
      { type: "paragraph", content: inlineToTiptap(item.inline, "") },
      ...(item.blocks ?? []).map((block) => elementToNode(block, resolvedStyles, true)),
    ];
    if (index > nestedStart) {
      const nested = buildNestedListItems(items.slice(nestedStart, index), level + 1, kind, resolvedStyles);
      if (nested.length > 0) {
        children.push({ type: LIST_NODE[kind], content: nested });
      }
    }
    nodes.push(kind === "task" ? { type: "taskItem", attrs: { checked: Boolean(item.checked) }, content: children } : { type: "listItem", content: children });
  }
  return nodes;
}

/** The grid column each cell starts in, spans taken into account. */
export function cellColumns(table: TableContent): number[][] {
  const occupied = new Set<string>();
  return table.rows.map((row, rowIndex) => {
    let column = 0;
    return row.cells.map((cell) => {
      while (occupied.has(`${rowIndex}:${column}`)) column += 1;
      const start = column;
      for (let dr = 0; dr < cell.rowspan; dr += 1) {
        for (let dc = 0; dc < cell.colspan; dc += 1) occupied.add(`${rowIndex + dr}:${start + dc}`);
      }
      column += cell.colspan;
      return start;
    });
  });
}

function tableElementToNode(el: Element, nodeAttrs: TiptapNode, resolvedStyles: ResolvedStyles): TiptapNode {
  const table = el.table;
  if (!table) return paragraphNode(el, nodeAttrs);
  const columns = cellColumns(table);
  return {
    type: "table",
    attrs: nodeAttrs,
    content: table.rows.map((row, rowIndex) => ({
      type: "tableRow",
      content: row.cells.map((cell, cellIndex) => {
        const alignment = table.alignments?.[columns[rowIndex][cellIndex]] ?? null;
        return {
          type: cell.header ? "tableHeader" : "tableCell",
          attrs: { colspan: cell.colspan, rowspan: cell.rowspan, backgroundColor: cell.background ?? null },
          content: cell.blocks?.length
            ? cellBlocksToNodes(cell.blocks, alignment, resolvedStyles)
            : [{ type: "paragraph", attrs: alignment ? { textAlign: alignment } : {}, content: inlineToTiptap(cell.inline, "") }],
        };
      }),
    })),
  };
}

/** A cell's blocks; its column's alignment goes on its first paragraph, the one
 * the column alignment is read back from. */
function cellBlocksToNodes(blocks: Element[], alignment: string | null, resolvedStyles: ResolvedStyles): TiptapNode[] {
  const nodes = blocks.map((block) => elementToNode(block, resolvedStyles, true));
  const firstParagraph = nodes.find((node) => node.type === "paragraph");
  if (firstParagraph && alignment) firstParagraph.attrs = { ...(firstParagraph.attrs as TiptapNode), textAlign: alignment };
  return nodes;
}

function inlineToTiptap(inline: InlineRun[] | null, fallbackText: string): TiptapNode[] {
  const runs = inline && inline.length > 0 ? inline : fallbackText ? [{ text: fallbackText, marks: [] }] : [];
  const nodes: TiptapNode[] = [];
  for (const run of runs) {
    const marks = run.marks.map(markToTiptap).filter((mark): mark is TiptapNode => mark !== null);
    // A line break inside a paragraph ("\n" in the model) is a hardBreak node.
    run.text.split("\n").forEach((line, index) => {
      if (index > 0) nodes.push({ type: "hardBreak" });
      if (line.length > 0) nodes.push({ type: "text", text: line, ...(marks.length > 0 ? { marks } : {}) });
    });
  }
  return nodes;
}

function markToTiptap(mark: Mark): TiptapNode | null {
  switch (mark.type) {
    case "bold":
      return { type: "bold" };
    case "italic":
      return { type: "italic" };
    case "underline":
      return mark.lineStyle ? { type: "underline", attrs: { lineStyle: mark.lineStyle } } : { type: "underline" };
    case "strike":
      return mark.lineStyle ? { type: "strike", attrs: { lineStyle: mark.lineStyle } } : { type: "strike" };
    case "code":
      return { type: "code" };
    case "link":
      return { type: "link", attrs: { href: mark.href ?? "", title: mark.title ?? null } };
    case "superscript":
      return { type: "superscript" };
    case "subscript":
      return { type: "subscript" };
    case "hidden":
      return { type: "hidden" };
    case "textStyle": {
      const attrs = {
        fontFamily: mark.fontFamily ? cssFontStack(mark.fontFamily) : null,
        fontSize: mark.fontSizePt ? `${mark.fontSizePt}pt` : null,
        color: mark.color ?? null,
        backgroundColor: mark.backgroundColor ?? null,
        caps: mark.caps ? true : null,
        smallCaps: mark.smallCaps ? true : null,
        letterSpacing: mark.letterSpacingPt ? `${mark.letterSpacingPt}pt` : null,
        baselineShift: mark.baselineShiftPt ? `${mark.baselineShiftPt}pt` : null,
        lang: mark.lang ?? null,
      };
      return Object.values(attrs).some((value) => value !== null) ? { type: "textStyle", attrs } : null;
    }
    default:
      return null;
  }
}
