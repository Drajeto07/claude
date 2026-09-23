import type { Document, Element, ElementType, InlineRun, ListItem, Mark } from "@/types/document";

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
};

// Ported 1:1 from the backend's target_for_element (app/models/document.py) --
// must stay in lockstep, since this is the join key into resolvedStyles.
function targetForElement(el: Element): string {
  if (el.type === "heading") return `Heading ${el.level ?? 1}`;
  return _ELEMENT_TYPE_TO_TARGET[el.type] ?? "Paragraph";
}

function styleAttrFor(el: Element, resolvedStyles: ResolvedStyles): TiptapNode {
  const css = resolvedStyles[el.styleRef ?? targetForElement(el)];
  if (!css || Object.keys(css).length === 0) return {};
  return { style: Object.entries(css).map(([property, value]) => `${property}:${value}`).join(";") };
}

export function documentToTiptapJSON(doc: Document): TiptapNode {
  const sorted = [...doc.elements].sort((a, b) => a.order - b.order);
  return { type: "doc", content: sorted.map((el) => elementToNode(el, doc.resolvedStyles)) };
}

function elementToNode(el: Element, resolvedStyles: ResolvedStyles): TiptapNode {
  const confidenceAttrs = el.confidence !== null ? { confidence: el.confidence } : {};
  const nodeAttrs: TiptapNode = { elementId: el.id, ...confidenceAttrs, ...styleAttrFor(el, resolvedStyles) };

  switch (el.type) {
    case "heading":
      return {
        type: "heading",
        attrs: { level: el.level ?? 1, ...nodeAttrs },
        content: inlineToTiptap(el.inline, el.content),
      };
    case "list":
      return listElementToNode(el, nodeAttrs);
    case "table":
      return tableElementToNode(el, nodeAttrs);
    case "image":
      return el.image
        ? {
            type: "image",
            attrs: { src: el.image.src, alt: el.image.alt ?? undefined, title: el.image.title ?? undefined, ...nodeAttrs },
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
        content: [{ type: "paragraph", content: inlineToTiptap(el.inline, el.content) }],
      };
    case "page_break":
      return { type: "pageBreak", attrs: nodeAttrs };
    // paragraph/caption/footnote/other: no dedicated Tiptap node type exists
    // (or is worth adding) for caption/footnote/other yet -- render as a
    // plain paragraph, same as Phase 1's existing fallback behavior.
    default:
      return paragraphNode(el, nodeAttrs);
  }
}

function paragraphNode(el: Element, nodeAttrs: TiptapNode): TiptapNode {
  return {
    type: "paragraph",
    attrs: nodeAttrs,
    content: inlineToTiptap(el.inline, el.content),
  };
}

function listElementToNode(el: Element, nodeAttrs: TiptapNode): TiptapNode {
  const items = el.listItems ?? [];
  return {
    type: el.ordered ? "orderedList" : "bulletList",
    attrs: nodeAttrs,
    content: buildNestedListItems(items, 0, el.ordered),
  };
}

// Groups a flat [{level:0}, {level:1}, {level:1}, {level:0}, ...] array into
// a nested Tiptap listItem tree -- the backend flattens nesting depth into
// ListItem.level rather than a recursive structure (see Document Model
// design notes), so this is the inverse projection back into a real tree.
function buildNestedListItems(items: ListItem[], level: number, ordered: boolean): TiptapNode[] {
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
    const children: TiptapNode[] = [{ type: "paragraph", content: checklistAwareInline(item) }];
    if (index > nestedStart) {
      const nested = buildNestedListItems(items.slice(nestedStart, index), level + 1, ordered);
      if (nested.length > 0) {
        children.push({ type: ordered ? "orderedList" : "bulletList", content: nested });
      }
    }
    nodes.push({ type: "listItem", content: children });
  }
  return nodes;
}

// No TaskList/TaskItem extension is installed this phase (checklists are a
// minor detail within lists, not a primary element type) -- a visible
// checkbox glyph keeps the checked/unchecked information without adding a
// dependency beyond what the approved plan scoped.
function checklistAwareInline(item: ListItem): TiptapNode[] {
  const content = inlineToTiptap(item.inline, "");
  if (item.checked === null) return content;
  const prefix = item.checked ? "☑ " : "☐ ";
  return [{ type: "text", text: prefix }, ...content];
}

function tableElementToNode(el: Element, nodeAttrs: TiptapNode): TiptapNode {
  const table = el.table;
  if (!table) return paragraphNode(el, nodeAttrs);
  return {
    type: "table",
    attrs: nodeAttrs,
    content: table.rows.map((row) => ({
      type: "tableRow",
      content: row.cells.map((cell) => ({
        type: cell.header ? "tableHeader" : "tableCell",
        content: [{ type: "paragraph", content: inlineToTiptap(cell.inline, "") }],
      })),
    })),
  };
}

function inlineToTiptap(inline: InlineRun[] | null, fallbackText: string): TiptapNode[] {
  const runs = inline && inline.length > 0 ? inline : fallbackText ? [{ text: fallbackText, marks: [] }] : [];
  return runs
    .filter((run) => run.text.length > 0)
    .map((run) => ({
      type: "text",
      text: run.text,
      ...(run.marks.length > 0 ? { marks: run.marks.map(markToTiptap) } : {}),
    }));
}

function markToTiptap(mark: Mark): TiptapNode {
  switch (mark.type) {
    case "bold":
      return { type: "bold" };
    case "italic":
      return { type: "italic" };
    case "strike":
      return { type: "strike" };
    case "code":
      return { type: "code" };
    case "link":
      return { type: "link", attrs: { href: mark.href ?? "" } };
  }
}
