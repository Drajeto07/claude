import { assetIdFromUrl } from "@/services/api";
import type { Element, ElementType, ImageContent, InlineRun, ListItem, Mark, MarkType, TableCell, TableContent, TableRow } from "@/types/document";

type TiptapNode = {
  type?: string;
  text?: string;
  attrs?: Record<string, unknown>;
  content?: TiptapNode[];
  marks?: { type: string; attrs?: Record<string, unknown> }[];
};

const _SIMPLE_MARKS: MarkType[] = ["bold", "italic", "underline", "strike", "code", "superscript", "subscript"];
// The colour names the backend and both exporters understand (backend app/formatting/colors.py).
const _NAMED_COLORS = new Set(["red", "blue", "green", "black", "white", "gray", "grey", "yellow", "orange", "purple"]);

// Values pasted content or the browser can put on a textStyle mark ("rgb(…)",
// font stacks, px sizes) normalized to what the Document Model accepts; anything
// else is dropped rather than failing the save.
export function normalizeColor(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (/^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(text)) return text.toUpperCase();
  const rgb = text.match(/^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([\d.]+)\s*)?\)$/i);
  if (rgb) {
    if (rgb[4] !== undefined && Number(rgb[4]) === 0) return null; // fully transparent
    return `#${[rgb[1], rgb[2], rgb[3]].map((part) => Math.min(255, Number(part)).toString(16).padStart(2, "0")).join("")}`.toUpperCase();
  }
  return _NAMED_COLORS.has(text.toLowerCase()) ? text.toLowerCase() : null;
}

export function normalizeFont(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const first = value.split(",")[0].trim().replace(/^["']|["']$/g, "").trim();
  return first.length <= 100 && /^[\p{L}\p{N}_][\p{L}\p{N}_ .-]*$/u.test(first) ? first : null;
}

export function normalizeSizePt(value: unknown): number | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const match = String(value).trim().match(/^(\d+(?:\.\d+)?)\s*(pt|px)?$/i);
  if (!match) return null;
  const size = Number(match[1]) * (match[2]?.toLowerCase() === "px" ? 0.75 : 1);
  return size > 0 && size <= 400 ? Math.round(size * 100) / 100 : null;
}

// A mark's fields besides its type; only links and textStyle marks set any.
const _UNSET = { href: null, fontFamily: null, fontSizePt: null, color: null, backgroundColor: null } as const;

function marksFromTiptap(marks: TiptapNode["marks"]): Mark[] {
  if (!marks) return [];
  const result: Mark[] = [];
  for (const mark of marks) {
    if ((_SIMPLE_MARKS as string[]).includes(mark.type)) {
      result.push({ ..._UNSET, type: mark.type as MarkType });
    } else if (mark.type === "link") {
      result.push({ ..._UNSET, type: "link", href: (mark.attrs?.href as string) ?? null });
    } else if (mark.type === "textStyle") {
      const style = {
        fontFamily: normalizeFont(mark.attrs?.fontFamily),
        fontSizePt: normalizeSizePt(mark.attrs?.fontSize),
        color: normalizeColor(mark.attrs?.color),
        backgroundColor: normalizeColor(mark.attrs?.backgroundColor),
      };
      if (Object.values(style).some((value) => value !== null)) result.push({ ..._UNSET, type: "textStyle", ...style });
    }
  }
  return result;
}

function inlineFromContent(content: TiptapNode[] | undefined): InlineRun[] {
  const runs: InlineRun[] = [];
  for (const node of content ?? []) {
    let run: InlineRun | null = null;
    if (node.type === "text" && typeof node.text === "string") run = { text: node.text, marks: marksFromTiptap(node.marks) };
    else if (node.type === "hardBreak") run = { text: "\n", marks: [] };
    if (!run) continue;
    const previous = runs[runs.length - 1];
    if (previous && JSON.stringify(previous.marks) === JSON.stringify(run.marks)) previous.text += run.text;
    else runs.push(run);
  }
  return runs;
}

/** Several paragraphs (a table cell, a quote, a list item) as one run list, joined by line breaks. */
function inlineFromParagraphs(nodes: TiptapNode[] | undefined): InlineRun[] {
  const paragraphs = (nodes ?? []).filter((node) => node.type === "paragraph" || node.type === "heading");
  const runs: InlineRun[] = [];
  paragraphs.forEach((paragraph, index) => {
    if (index > 0) runs.push({ text: "\n", marks: [] });
    runs.push(...inlineFromContent(paragraph.content));
  });
  return runs;
}

function plainText(inline: InlineRun[]): string {
  return inline.map((run) => run.text).join("");
}

const _LIST_NODES = new Set(["bulletList", "orderedList", "taskList"]);

function flattenListItems(content: TiptapNode[] | undefined, level: number): ListItem[] {
  const items: ListItem[] = [];
  for (const listItem of content ?? []) {
    const children = listItem.content ?? [];
    const nestedList = children.find((child) => _LIST_NODES.has(child.type ?? ""));
    const checked = listItem.type === "taskItem" ? Boolean(listItem.attrs?.checked) : null;
    items.push({ id: crypto.randomUUID(), inline: inlineFromParagraphs(children), level, checked });
    if (nestedList) items.push(...flattenListItems(nestedList.content, level + 1));
  }
  return items;
}

function tableContentFromNode(node: TiptapNode): TableContent {
  const occupied = new Set<string>();
  const alignmentsByColumn = new Map<number, Set<string | null>>();
  const rows: TableRow[] = (node.content ?? []).map((row, rowIndex) => {
    let column = 0;
    const cells: TableCell[] = (row.content ?? []).map((cell) => {
      const colspan = Math.max(1, Number(cell.attrs?.colspan ?? 1) || 1);
      const rowspan = Math.max(1, Number(cell.attrs?.rowspan ?? 1) || 1);
      while (occupied.has(`${rowIndex}:${column}`)) column += 1;
      for (let dr = 0; dr < rowspan; dr += 1) {
        for (let dc = 0; dc < colspan; dc += 1) occupied.add(`${rowIndex + dr}:${column + dc}`);
      }
      const firstParagraph = cell.content?.find((child) => child.type === "paragraph");
      const alignment = (firstParagraph?.attrs?.textAlign as string | null | undefined) ?? null;
      if (!alignmentsByColumn.has(column)) alignmentsByColumn.set(column, new Set());
      alignmentsByColumn.get(column)!.add(alignment);
      column += colspan;
      return {
        id: crypto.randomUUID(),
        inline: inlineFromParagraphs(cell.content),
        header: cell.type === "tableHeader",
        colspan,
        rowspan,
        background: normalizeColor(cell.attrs?.backgroundColor),
      };
    });
    return { id: crypto.randomUUID(), cells };
  });
  const width = Math.max(0, ...[...alignmentsByColumn.keys()].map((column) => column + 1));
  // A column alignment is kept when every cell starting in that column agrees on it.
  const alignments = Array.from({ length: width }, (_, column) => {
    const seen = alignmentsByColumn.get(column);
    return seen && seen.size === 1 ? [...seen][0] : null;
  });
  const hasHeaderRow = rows.length > 0 && rows[0].cells.every((cell) => cell.header);
  return { rows, hasHeaderRow, alignments: alignments.some((value) => value !== null) ? alignments : null };
}

function imageContentFromNode(node: TiptapNode): ImageContent {
  const attrs = node.attrs ?? {};
  const src = (attrs.src as string) ?? "";
  const assetId = assetIdFromUrl(src);
  return {
    src: assetId ? "" : src,
    assetId,
    alt: (attrs.alt as string) ?? null,
    title: (attrs.title as string) ?? null,
  };
}

type Derived = {
  type: ElementType;
  content: string;
  inline: InlineRun[] | null;
  listItems: ListItem[] | null;
  ordered: boolean;
  table: TableContent | null;
  image: ImageContent | null;
  language: string | null;
  level: number | null;
};

const _EMPTY: Omit<Derived, "type" | "content"> = { inline: null, listItems: null, ordered: false, table: null, image: null, language: null, level: null };

// The inverse of documentToTiptap.ts's elementToNode -- given a live Tiptap
// node, derives the Element fields that come from its editable content.
// Returns null for a node type this reconciliation doesn't (yet) reconstruct
// from scratch -- deliberately scoped to top-level block content/structure
// (see the plan's Stage 0 note).
function deriveFromNode(node: TiptapNode): Derived | null {
  switch (node.type) {
    case "heading": {
      const inline = inlineFromContent(node.content);
      return { ..._EMPTY, type: "heading", content: plainText(inline), inline, level: (node.attrs?.level as number) ?? 1 };
    }
    case "paragraph": {
      const inline = inlineFromContent(node.content);
      return { ..._EMPTY, type: "paragraph", content: plainText(inline), inline };
    }
    case "caption":
    case "footnote": {
      const inline = inlineFromContent(node.content);
      return { ..._EMPTY, type: node.type, content: plainText(inline), inline };
    }
    case "blockquote": {
      const inline = inlineFromParagraphs(node.content);
      return { ..._EMPTY, type: "quote", content: plainText(inline), inline };
    }
    case "codeBlock": {
      const text = (node.content ?? []).map((child) => child.text ?? "").join("");
      return { ..._EMPTY, type: "code_block", content: text, language: (node.attrs?.language as string) ?? null };
    }
    case "bulletList":
    case "orderedList":
    case "taskList": {
      const listItems = flattenListItems(node.content, 0);
      return {
        ..._EMPTY,
        type: "list",
        content: listItems.map((item) => plainText(item.inline)).join("\n"),
        listItems,
        ordered: node.type === "orderedList",
      };
    }
    case "table": {
      const table = tableContentFromNode(node);
      return {
        ..._EMPTY,
        type: "table",
        // Cells joined as every backend producer joins them (the importers, structure analysis),
        // so opening and saving a document doesn't rewrite its tables' summaries.
        content: table.rows.map((row) => row.cells.map((cell) => plainText(cell.inline)).join(" | ")).join("\n"),
        table,
      };
    }
    case "image":
      return { ..._EMPTY, type: "image", content: "", image: imageContentFromNode(node) };
    case "pageBreak":
      return { ..._EMPTY, type: "page_break", content: "" };
    case "horizontalRule":
      return { ..._EMPTY, type: "horizontal_rule", content: "" };
    default:
      return null;
  }
}

/**
 * Reconciles the editor's *current* Tiptap JSON against the last-known
 * elements: an existing elementId gets its content/structure refreshed in
 * place (everything else about it -- styleRef, confidence, id -- untouched);
 * a node with no elementId (the user pressed Enter and created a new block)
 * becomes a new Element at that position; an id that no longer appears was
 * deleted. Order is reassigned by final position, matching the array order
 * DocumentEditor already renders in. An id seen twice (a block copied or split
 * with its attributes) is a new element the second time.
 */
export function reconcileElements(tiptapContent: TiptapNode[], currentElements: Element[]): Element[] {
  return reconcileWithIds(tiptapContent, currentElements).elements;
}

/**
 * reconcileElements, plus the element id each top-level node ended up with
 * (null for a node that isn't an element) -- written back into the editor, so a
 * new block keeps the same id from one save to the next.
 */
export function reconcileWithIds(
  tiptapContent: TiptapNode[],
  currentElements: Element[],
): { elements: Element[]; nodeIds: (string | null)[] } {
  const byId = new Map(currentElements.map((el) => [el.id, el]));
  const owners = identityOwners(tiptapContent, byId);
  const result: Element[] = [];
  const nodeIds: (string | null)[] = [];
  const end = contentEnd(tiptapContent);

  tiptapContent.forEach((node, index) => {
    if (index >= end) {
      nodeIds.push(null);
      return;
    }
    const elementId = (node.attrs?.elementId as string | undefined) ?? undefined;
    const existing = elementId && owners.get(elementId) === index ? byId.get(elementId) : undefined;
    const derived = deriveFromNode(node);
    nodeIds.push(null);
    if (!derived) return; // unrecognized node type -- leave whatever existed there out rather than guess

    if (existing) {
      keepPartIds(derived, existing);
      // Image nodes are atoms, so the same element can't have a different picture:
      // a pasted data: URI the server has already stored is that stored asset.
      // Without this, every autosave would re-send and re-store the same bytes.
      if (derived.image?.src.startsWith("data:") && existing.image?.assetId) {
        derived.image = existing.image;
      }
      result.push({ ...existing, ...derived, order: result.length });
    } else {
      result.push({
        id: crypto.randomUUID(),
        parentId: null,
        confidence: null,
        styleRef: null,
        preservedAttributes: null,
        order: result.length,
        ...derived,
      });
    }
    nodeIds[index] = result[result.length - 1].id;
  });
  return { elements: result, nodeIds };
}

/** Where the document's content ends: the editor keeps an empty paragraph at the
 * very end so there's somewhere to type after a table or a picture (Tiptap's
 * trailing node). A blank one the document never had isn't part of it, so it
 * isn't saved -- opening a document and typing elsewhere adds nothing at its end. */
function contentEnd(content: TiptapNode[]): number {
  let end = content.length;
  while (end > 0) {
    const node = content[end - 1];
    const blank = node.type === "paragraph" && !node.attrs?.elementId && !(node.content ?? []).length;
    if (!blank) break;
    end -= 1;
  }
  return end;
}

/** List items, rows and cells keep the ids they had, position by position, so an
 * unchanged list or table compares equal and isn't saved again for nothing. */
function keepPartIds(derived: Derived, existing: Element) {
  if (derived.listItems && existing.listItems) {
    const previous = existing.listItems;
    derived.listItems = derived.listItems.map((item, index) => ({ ...item, id: previous[index]?.id ?? item.id }));
  }
  if (derived.table && existing.table) {
    const previousRows = existing.table.rows;
    derived.table = {
      ...derived.table,
      rows: derived.table.rows.map((row, rowIndex) => ({
        ...row,
        id: previousRows[rowIndex]?.id ?? row.id,
        cells: row.cells.map((cell, cellIndex) => ({ ...cell, id: previousRows[rowIndex]?.cells[cellIndex]?.id ?? cell.id })),
      })),
    };
  }
}

/** Equal as the Document Model sees it: key order doesn't matter, and a field that
 * is null, absent or an empty list is the same (a page break's `inline: []` from the
 * importer is the editor's none). */
export function sameContent(a: unknown, b: unknown): boolean {
  return canonical(a) === canonical(b);
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== null && item !== undefined && !(Array.isArray(item) && item.length === 0))
      .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0));
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  }
  return JSON.stringify(value ?? null);
}

/**
 * Which node keeps each element id. Splitting a block anywhere but at its end
 * copies the id onto both halves; the half that kept more of the original text
 * keeps the element (and its own formatting), the other becomes a new one.
 */
function identityOwners(nodes: TiptapNode[], byId: Map<string, Element>): Map<string, number> {
  const owners = new Map<string, number>();
  const bestScore = new Map<string, number>();
  nodes.forEach((node, index) => {
    const id = node.attrs?.elementId as string | undefined;
    const existing = id ? byId.get(id) : undefined;
    if (!id || !existing) return;
    const score = sharedEnds(deriveFromNode(node)?.content ?? "", existing.content);
    if (!owners.has(id) || score > (bestScore.get(id) ?? -1)) {
      owners.set(id, index);
      bestScore.set(id, score);
    }
  });
  return owners;
}

/** How much of `original` a split half kept: its longest shared start or end. */
function sharedEnds(text: string, original: string): number {
  let prefix = 0;
  while (prefix < text.length && prefix < original.length && text[prefix] === original[prefix]) prefix += 1;
  let suffix = 0;
  while (suffix < text.length && suffix < original.length && text[text.length - 1 - suffix] === original[original.length - 1 - suffix]) suffix += 1;
  return Math.max(prefix, suffix);
}
