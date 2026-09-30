import { targetForElement } from "@/editor/documentToTiptap";
import { assetIdFromUrl } from "@/services/api";
import type {
  DirectStyle,
  Document,
  Element,
  ElementType,
  ImageContent,
  InlineRun,
  ListItem,
  ListNumbering,
  Mark,
  MarkType,
  NumberFormat,
  TableCell,
  TableContent,
  TableRow,
} from "@/types/document";
import { LINE_STYLES } from "./characterFormatting";
import { safeHref } from "./linkPolicy";
import type { ListNumberingAttr } from "./listNumbering";
import { NO_PICTURE, type PictureAttr } from "./pictureLook";
import { CM_TO_PX, PLAIN_TABLE, type CellLookAttr, type RowLookAttr, type TableLookAttr } from "./tableLook";

type TiptapNode = {
  type?: string;
  text?: string;
  attrs?: Record<string, unknown>;
  content?: TiptapNode[];
  marks?: { type: string; attrs?: Record<string, unknown> }[];
};

/**
 * The editor holds something the Document Model can't store -- a node or a mark
 * this mapping doesn't know. Saving stops with this error rather than leaving it
 * out: nothing in the editor is ever dropped on its way to the server.
 */
export class UnsupportedContentError extends Error {
  constructor(
    readonly what: string,
    readonly where: string,
  ) {
    super(`The document contains ${what}${where ? ` ${where}` : ""} that can't be saved yet.`);
    this.name = "UnsupportedContentError";
  }
}

/** Formatting the editor holds that the document can't keep: saving goes on
 * without it, and the editor says so (the notes reconcileWithIds returns). */
export const NOT_KEPT = {
  color: "Colours the document can't store (such as hsl() or theme colours) weren't kept.",
  font: "A font the document can't store by its name wasn't kept.",
  size: "Font sizes the document can't store (such as em or % sizes) weren't kept.",
  nestedAlignment: "Alignment inside lists, quotes and table cells isn't kept.",
  nestedPictureSize: "Picture sizes inside lists, quotes and table cells aren't kept.",
  pictureSize: "A picture size the document can't store wasn't kept.",
  linkTitle: "A link title longer than 500 characters was shortened.",
  link: "A link to an address a document can't open (a relative one, or javascript: and the like) is kept as its text only.",
  spacing: "Character spacing or a raised or lowered baseline the document can't store (such as em values) wasn't kept.",
} as const;

// The notes of the reconcile under way (reconcileWithIds sets and clears it).
let notes: Set<string> | null = null;

function note(text: string) {
  notes?.add(text);
}

/** Set to something: a value pasted content or the editor put there. */
function given(value: unknown): boolean {
  return value !== null && value !== undefined && String(value).trim() !== "";
}

/** No colour at all ("transparent", zero alpha): nothing is lost when it goes. */
function transparent(value: unknown): boolean {
  const text = String(value).trim().toLowerCase();
  return text === "transparent" || /^rgba\(.*,\s*0(?:\.0+)?\s*\)$/.test(text);
}

const _SIMPLE_MARKS: MarkType[] = ["bold", "italic", "code", "superscript", "subscript", "hidden"];
/** The order the backend keeps a run's marks in (its MarkType), so a run the editor
 * lists its own way isn't a change to save (tracker EDIT-007). */
export const MARK_ORDER: MarkType[] = ["bold", "italic", "underline", "strike", "code", "link", "superscript", "subscript", "textStyle", "hidden"];
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

// A mark's fields besides its type; only links, lines (underline, strike) and textStyle marks set any.
const _UNSET = {
  href: null,
  title: null,
  lineStyle: null,
  fontFamily: null,
  fontSizePt: null,
  color: null,
  backgroundColor: null,
  caps: null,
  smallCaps: null,
  letterSpacingPt: null,
  baselineShiftPt: null,
  lang: null,
} as const;

/** A language tag as the model keeps it ("bg-BG"); Word's "x-none" (no language) and anything else, none. */
export function normalizeLang(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const tag = value.trim();
  return tag.length <= 35 && /^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$/.test(tag) ? tag : null;
}

/** Character spacing or a baseline shift as the model keeps it: points, within ±100. */
export function normalizeOffsetPt(value: unknown): number | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const match = String(value).trim().match(/^(-?\d+(?:\.\d+)?)\s*(pt|px)?$/i);
  if (!match) return null;
  const points = Number(match[1]) * (match[2]?.toLowerCase() === "px" ? 0.75 : 1);
  return points !== 0 && Math.abs(points) <= 100 ? Math.round(points * 100) / 100 : null;
}

/** No spacing or shift at all ("normal", "0pt"): nothing is lost when it goes. */
function noOffset(value: unknown): boolean {
  const text = String(value).trim().toLowerCase();
  return text === "normal" || text === "baseline" || /^[-+]?0+(\.0+)?[a-z%]*$/.test(text);
}

function lineStyle(value: unknown, allowed: readonly string[]): Mark["lineStyle"] {
  return typeof value === "string" && allowed.includes(value) ? (value as Mark["lineStyle"]) : null;
}
const _MAX_LINK_TITLE = 500;

/** A link's title (tooltip) as the model keeps it: one line, at most 500 characters. */
function linkTitle(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const title = value.split(/\s+/).filter(Boolean).join(" ");
  if (title.length > _MAX_LINK_TITLE) note(NOT_KEPT.linkTitle);
  return title.slice(0, _MAX_LINK_TITLE) || null;
}

function marksFromTiptap(marks: TiptapNode["marks"], where: string): Mark[] {
  if (!marks) return [];
  const result: Mark[] = [];
  for (const mark of marks) {
    if ((_SIMPLE_MARKS as string[]).includes(mark.type)) {
      result.push({ ..._UNSET, type: mark.type as MarkType });
    } else if (mark.type === "underline") {
      result.push({ ..._UNSET, type: "underline", lineStyle: lineStyle(mark.attrs?.lineStyle, LINE_STYLES) });
    } else if (mark.type === "strike") {
      result.push({ ..._UNSET, type: "strike", lineStyle: lineStyle(mark.attrs?.lineStyle, ["double"]) });
    } else if (mark.type === "link") {
      // The backend keeps no other address either (SEC-014): its text stays, said to.
      const href = safeHref(mark.attrs?.href as string | undefined);
      if (href) result.push({ ..._UNSET, type: "link", href, title: linkTitle(mark.attrs?.title) });
      else note(NOT_KEPT.link);
    } else if (mark.type === "textStyle") {
      const attrs = mark.attrs ?? {};
      const style = {
        fontFamily: normalizeFont(attrs.fontFamily),
        fontSizePt: normalizeSizePt(attrs.fontSize),
        color: normalizeColor(attrs.color),
        backgroundColor: normalizeColor(attrs.backgroundColor),
        caps: attrs.caps ? true : null,
        smallCaps: attrs.smallCaps && !attrs.caps ? true : null,
        letterSpacingPt: normalizeOffsetPt(attrs.letterSpacing),
        baselineShiftPt: normalizeOffsetPt(attrs.baselineShift),
        lang: normalizeLang(attrs.lang),
      };
      for (const [key, attribute] of [["letterSpacingPt", "letterSpacing"], ["baselineShiftPt", "baselineShift"]] as const) {
        if (given(attrs[attribute]) && style[key] === null && !noOffset(attrs[attribute])) note(NOT_KEPT.spacing);
      }
      if (given(attrs.fontFamily) && style.fontFamily === null) note(NOT_KEPT.font);
      if (given(attrs.fontSize) && style.fontSizePt === null) note(NOT_KEPT.size);
      for (const key of ["color", "backgroundColor"] as const) {
        if (given(attrs[key]) && style[key] === null && !transparent(attrs[key])) note(NOT_KEPT.color);
      }
      if (Object.values(style).some((value) => value !== null)) result.push({ ..._UNSET, type: "textStyle", ...style });
    } else {
      throw new UnsupportedContentError(`"${mark.type}" formatting`, where);
    }
  }
  return result.sort((a, b) => MARK_ORDER.indexOf(a.type) - MARK_ORDER.indexOf(b.type));
}

function inlineFromContent(content: TiptapNode[] | undefined, where: string): InlineRun[] {
  const runs: InlineRun[] = [];
  for (const node of content ?? []) {
    let run: InlineRun;
    if (node.type === "text") run = { text: node.text ?? "", marks: marksFromTiptap(node.marks, where) };
    else if (node.type === "hardBreak") run = { text: "\n", marks: [] };
    else throw new UnsupportedContentError(describe(node), where);
    if (!run.text) continue;
    const previous = runs[runs.length - 1];
    if (previous && JSON.stringify(previous.marks) === JSON.stringify(run.marks)) previous.text += run.text;
    else runs.push(run);
  }
  return runs;
}

function describe(node: TiptapNode): string {
  return `content of type "${node.type ?? "unknown"}"`;
}

/** A paragraph or heading inside a container: its alignment has nowhere to go. */
function noteNestedAlignment(node: TiptapNode | null | undefined) {
  if (node && given(node.attrs?.textAlign)) note(NOT_KEPT.nestedAlignment);
}

function plainText(inline: InlineRun[]): string {
  return inline.map((run) => run.text).join("");
}

/** The words of several blocks, one per line: a container's plain text. */
function blocksText(blocks: Element[]): string {
  return blocks
    .map((block) => block.content)
    .filter((text) => text.length > 0)
    .join("\n");
}

const _ITEM_NODES = new Set(["listItem", "taskItem"]);
const _FORMAT_BY_TYPE: Record<string, NumberFormat> = { "1": "decimal", a: "lowerLetter", A: "upperLetter", i: "lowerRoman", I: "upperRoman" };
const _MAX_START = 999_999;

/** A list's numbering -- an ordered list's start and format, and a list's own levels
 * from Word (listNumbering.ts, DOCX-016) -- or null when it counts 1, 2, 3 (or goes •, ◦, ▪). */
function numberingOf(node: TiptapNode): ListNumbering | null {
  const own = (node.attrs?.numbering ?? null) as ListNumberingAttr | null;
  const levels = own?.levels ?? null;
  if (node.type === "bulletList") return levels ? { start: 1, format: "decimal", levels } : null;
  if (node.type !== "orderedList") return null;
  const raw = Number(node.attrs?.start ?? 1);
  const start = Number.isFinite(raw) ? Math.trunc(raw) : 1;
  if (start < 0 || start > _MAX_START) throw new UnsupportedContentError(`a list numbered from ${start}`, "");
  // The HTML list type the editor shows; without one, a format it can't say (01, а) is the list's own.
  const type = node.attrs?.type;
  const format = type ? (_FORMAT_BY_TYPE[String(type)] ?? "decimal") : (own?.format ?? "decimal");
  return start === 1 && format === "decimal" && !levels ? null : { start, format, levels };
}

/** A sub-list at the end of an item that counts like its list nests as deeper
 * levels (the shape the importers and exporters use); any other stays a block. */
function nestsAsLevels(node: TiptapNode | undefined, listType: string): node is TiptapNode {
  return node !== undefined && node.type === listType && numberingOf(node) === null;
}

function collectItems(list: TiptapNode, level: number, listType: string, into: ListItem[]) {
  for (const item of list.content ?? []) {
    if (!_ITEM_NODES.has(item.type ?? "")) throw new UnsupportedContentError(describe(item), "in a list");
    const children = item.content ?? [];
    const lead = children[0]?.type === "paragraph" ? children[0] : null;
    noteNestedAlignment(lead);
    const rest = lead ? children.slice(1) : children;
    const sublist = nestsAsLevels(rest[rest.length - 1], listType) ? rest[rest.length - 1] : null;
    const blockNodes = sublist ? rest.slice(0, -1) : rest;
    into.push({
      id: crypto.randomUUID(),
      inline: lead ? inlineFromContent(lead.content, "in a list item") : [],
      level,
      checked: item.type === "taskItem" ? Boolean(item.attrs?.checked) : null,
      blocks: blockNodes.length > 0 ? nestedElements(blockNodes, "in a list item") : null,
    });
    if (sublist) collectItems(sublist, level + 1, listType, into);
  }
}

function listText(items: ListItem[]): string {
  return items.flatMap((item) => [plainText(item.inline), ...(item.blocks ? [blocksText(item.blocks)].filter(Boolean) : [])]).join("\n");
}

/** The paragraph a cell's alignment is read from (and written to): its column's. */
function alignmentParagraph(cell: TiptapNode): TiptapNode | undefined {
  return cell.content?.find((child) => child.type === "paragraph");
}

function cellFromNode(cell: TiptapNode): TableCell {
  const content = cell.content ?? [];
  const single = content.length === 1 && content[0].type === "paragraph";
  const own = (cell.attrs?.look ?? null) as CellLookAttr | null;
  // The first paragraph's alignment is the column's (tableContentFromNode), not a nested block's.
  const lead = alignmentParagraph(cell);
  const blocks = single
    ? null
    : nestedElements(
        content.map((node) => (node === lead ? { ...node, attrs: { ...node.attrs, textAlign: null } } : node)),
        "in a table cell",
      );
  const text = blocks ? blocksText(blocks) : "";
  return {
    id: crypto.randomUUID(),
    inline: single ? inlineFromContent(content[0].content, "in a table cell") : text ? [{ text, marks: [] }] : [],
    header: cell.type === "tableHeader",
    colspan: Math.max(1, Number(cell.attrs?.colspan ?? 1) || 1),
    rowspan: Math.max(1, Number(cell.attrs?.rowspan ?? 1) || 1),
    background: normalizeColor(cell.attrs?.backgroundColor),
    blocks,
    verticalAlign: own?.verticalAlign ?? null,
    align: null, // set from its paragraph where its column's cells differ (tableContentFromNode)
    borders: own?.borders ?? null,
    margins: own?.margins ?? null,
  };
}

const _CELL_ALIGNMENTS = new Set(["left", "center", "right", "justify"]);

function tableContentFromNode(node: TiptapNode): TableContent {
  const occupied = new Set<string>();
  const alignmentsByColumn = new Map<number, Set<string | null>>();
  const cellAlignments: [TableCell, number, string | null][] = [];
  let columnWidthsPx: number[] | null = null;
  const rows: TableRow[] = (node.content ?? []).map((row, rowIndex) => {
    if (row.type !== "tableRow") throw new UnsupportedContentError(describe(row), "in a table");
    let column = 0;
    const widthsPx: number[] = [];
    const cells: TableCell[] = (row.content ?? []).map((cellNode) => {
      if (cellNode.type !== "tableCell" && cellNode.type !== "tableHeader") throw new UnsupportedContentError(describe(cellNode), "in a table row");
      const cell = cellFromNode(cellNode);
      while (occupied.has(`${rowIndex}:${column}`)) column += 1;
      for (let dr = 0; dr < cell.rowspan; dr += 1) {
        for (let dc = 0; dc < cell.colspan; dc += 1) occupied.add(`${rowIndex + dr}:${column + dc}`);
      }
      // A cell's own alignment (pasted <td align>, or style) when its paragraph has none.
      const alignment = ((alignmentParagraph(cellNode)?.attrs?.textAlign ?? cellNode.attrs?.align) as string | null | undefined) ?? null;
      if (!alignmentsByColumn.has(column)) alignmentsByColumn.set(column, new Set());
      alignmentsByColumn.get(column)!.add(alignment);
      cellAlignments.push([cell, column, alignment]);
      const colwidth = cellNode.attrs?.colwidth;
      if (rowIndex === 0) widthsPx.push(...(Array.isArray(colwidth) ? colwidth.map(Number) : Array(cell.colspan).fill(NaN)));
      column += cell.colspan;
      return cell;
    });
    if (rowIndex === 0 && widthsPx.length && widthsPx.every((value) => Number.isFinite(value) && value > 0)) columnWidthsPx = widthsPx;
    const own = (row.attrs?.row ?? null) as RowLookAttr | null;
    return {
      id: crypto.randomUUID(),
      cells,
      heightCm: own?.heightCm ?? null,
      heightRule: own?.heightRule ?? "atLeast",
      repeatHeader: own?.repeatHeader ?? false,
      cantSplit: own?.cantSplit ?? false,
    };
  });
  const width = Math.max(0, ...[...alignmentsByColumn.keys()].map((column) => column + 1));
  // A column alignment is the one every cell starting in that column agrees on; where
  // they differ, each keeps its own (DOCX-017).
  const alignments = Array.from({ length: width }, (_, column) => {
    const seen = alignmentsByColumn.get(column);
    return seen && seen.size === 1 ? [...seen][0] : null;
  });
  for (const [cell, column, alignment] of cellAlignments) {
    if (alignments[column] === null && alignment && _CELL_ALIGNMENTS.has(alignment)) cell.align = alignment as TableCell["align"];
  }
  const hasHeaderRow = rows.length > 0 && rows[0].cells.every((cell) => cell.header);
  const look = (node.attrs?.look ?? null) as TableLookAttr | null;
  // Column widths: the table's own, unless the editor's differ (pasted ones, say).
  const widths = columnWidthsPx as number[] | null; // set in the rows' callback
  const keptWidths = look?.columnWidthsCm ?? null;
  const columnWidthsCm =
    widths && !(keptWidths && keptWidths.length === widths.length && keptWidths.every((cm, index) => Math.round(cm * CM_TO_PX) === widths[index]))
      ? widths.map((px) => Math.round((px / CM_TO_PX) * 100) / 100)
      : keptWidths;
  return {
    ...PLAIN_TABLE,
    ...(look ?? {}),
    columnWidthsCm,
    rows,
    hasHeaderRow,
    alignments: alignments.some((value) => value !== null) ? alignments : null,
  };
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
    // Its own look from Word (pictureLook.ts, DOCX-018), as it came in.
    ...NO_PICTURE,
    ...((attrs.picture ?? null) as PictureAttr | null),
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
  children: Element[] | null;
  numbering: ListNumbering | null;
  sectionBreak: Element["sectionBreak"];
  numbered: boolean | null;
};

const _EMPTY: Omit<Derived, "type" | "content"> = {
  inline: null,
  listItems: null,
  ordered: false,
  table: null,
  image: null,
  language: null,
  level: null,
  children: null,
  numbering: null,
  sectionBreak: null,
  numbered: null,
};

// The inverse of documentToTiptap.ts's elementToNode: the Element fields that come
// from a block's editable content, at any depth. Every node the editor's schema
// has is mapped; anything else stops the save (UnsupportedContentError).
function deriveFromNode(node: TiptapNode, where: string): Derived {
  switch (node.type) {
    case "heading": {
      if (where) noteNestedAlignment(node);
      const inline = inlineFromContent(node.content, where);
      const numbered = node.attrs?.numbered === false ? false : null; // DOCX-016A
      return { ..._EMPTY, type: "heading", content: plainText(inline), inline, level: (node.attrs?.level as number) ?? 1, numbered };
    }
    case "paragraph": {
      if (where) noteNestedAlignment(node);
      const inline = inlineFromContent(node.content, where);
      return { ..._EMPTY, type: "paragraph", content: plainText(inline), inline };
    }
    case "caption":
    case "footnote": {
      const inline = inlineFromContent(node.content, where);
      return { ..._EMPTY, type: node.type, content: plainText(inline), inline };
    }
    case "blockquote": {
      const content = node.content ?? [];
      if (content.length === 1 && content[0].type === "paragraph") {
        noteNestedAlignment(content[0]);
        const inline = inlineFromContent(content[0].content, "in a quote");
        return { ..._EMPTY, type: "quote", content: plainText(inline), inline };
      }
      const children = nestedElements(content, "in a quote");
      return { ..._EMPTY, type: "quote", content: blocksText(children), children };
    }
    case "codeBlock": {
      const text = (node.content ?? []).map((child) => child.text ?? "").join("");
      return { ..._EMPTY, type: "code_block", content: text, language: (node.attrs?.language as string) ?? null };
    }
    case "bulletList":
    case "orderedList":
    case "taskList": {
      const listItems: ListItem[] = [];
      collectItems(node, 0, node.type, listItems);
      return {
        ..._EMPTY,
        type: "list",
        content: listText(listItems),
        listItems,
        ordered: node.type === "orderedList",
        numbering: numberingOf(node),
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
      if (where && given(node.attrs?.width)) note(NOT_KEPT.nestedPictureSize);
      return { ..._EMPTY, type: "image", content: "", image: imageContentFromNode(node) };
    case "pageBreak":
      return { ..._EMPTY, type: "page_break", content: "" };
    case "sectionBreak": // its settings as they came (DOCX-015); the server checks them
      return { ..._EMPTY, type: "section_break", content: "", sectionBreak: (node.attrs?.section as Element["sectionBreak"]) ?? null };
    case "horizontalRule":
      return { ..._EMPTY, type: "horizontal_rule", content: "" };
    default:
      throw new UnsupportedContentError(describe(node), where);
  }
}

/** Blocks inside a cell, a list item or a quote, as elements of their own. */
function nestedElements(nodes: TiptapNode[], where: string): Element[] {
  return nodes.map((node, index) => ({
    id: crypto.randomUUID(),
    parentId: null,
    confidence: null,
    styleRef: null,
    preservedAttributes: null,
    sourceBlocks: null,
    sourceHash: null,
    ...deriveFromNode(node, where),
    order: index,
  }));
}

type Parts = Pick<Derived, "listItems" | "table" | "children" | "image">;

/** List items, rows, cells and nested blocks keep the ids (and, for nested blocks,
 * the styleRef, confidence and preserved data) they had, position by position, so an
 * unchanged list or table compares equal and isn't saved again for nothing. */
function adoptParts(derived: Parts, existing: Element) {
  if (derived.listItems && existing.listItems) {
    const previous = existing.listItems;
    derived.listItems = derived.listItems.map((item, index) => ({
      ...item,
      id: previous[index]?.id ?? item.id,
      blocks: adoptBlocks(item.blocks, previous[index]?.blocks),
    }));
  }
  if (derived.table && existing.table) {
    const previousRows = existing.table.rows;
    derived.table = {
      ...derived.table,
      rows: derived.table.rows.map((row, rowIndex) => ({
        ...row,
        id: previousRows[rowIndex]?.id ?? row.id,
        cells: row.cells.map((cell, cellIndex) => {
          const before = previousRows[rowIndex]?.cells[cellIndex];
          return { ...cell, id: before?.id ?? cell.id, blocks: adoptBlocks(cell.blocks, before?.blocks) };
        }),
      })),
    };
  }
  derived.children = adoptBlocks(derived.children, existing.children);
  // Image nodes are atoms, so the same element can't have a different picture:
  // a pasted data: URI the server has already stored is that stored asset.
  // Without this, every autosave would re-send and re-store the same bytes.
  if (derived.image?.src.startsWith("data:") && existing.image?.assetId) {
    derived.image = existing.image;
  }
}

function adoptBlocks(blocks: Element[] | null, before: Element[] | null | undefined): Element[] | null {
  if (!blocks) return null;
  return blocks.map((block, index) => {
    const previous = before?.[index];
    if (!previous || previous.type !== block.type) return block;
    const adopted: Element = {
      ...block,
      id: previous.id,
      parentId: previous.parentId,
      confidence: previous.confidence,
      styleRef: previous.styleRef,
      preservedAttributes: previous.preservedAttributes,
    };
    adoptParts(adopted, previous);
    return adopted;
  });
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
 *
 * Throws UnsupportedContentError when the editor holds anything the model can't
 * store, so the caller keeps the last saved version instead of a partial one.
 */
export function reconcileElements(tiptapContent: TiptapNode[], currentElements: Element[]): Element[] {
  return reconcileWithIds(tiptapContent, currentElements).elements;
}

/** What the page looks like: each element's resolved style, and the page's size
 * and margins (a picture's width in pixels becomes a share of the text width). */
export type Layout = Pick<Document, "resolvedStyles" | "settings">;

export type Reconciled = {
  elements: Element[];
  /** The element id each top-level node ended up with (null: not an element). */
  nodeIds: (string | null)[];
  /** Alignment and picture widths the editor holds on top-level blocks that their
   * elements don't have yet: saved as each element's own style. */
  styles: DirectStyle[];
  /** What the editor holds that the document can't keep (NOT_KEPT). */
  notes: string[];
};

const _ALIGNMENTS = new Set(["left", "center", "right", "justify"]);
const _PX_PER_MM = 96 / 25.4;

/** A picture's width ("300", "300px", "50%") as a percentage of the text width,
 * to one decimal; null when it can't be one. */
export function widthPercent(width: unknown, settings: Layout["settings"]): number | null {
  const match = String(width).trim().match(/^(\d+(?:\.\d+)?)\s*(px|%)?$/i);
  if (!match) return null;
  let percent = Number(match[1]);
  if (match[2] !== "%") {
    const textWidthMm = settings.pageWidthMm - 10 * (settings.marginLeftCm + settings.marginRightCm);
    if (!(textWidthMm > 0)) return null;
    percent = (Number(match[1]) / (textWidthMm * _PX_PER_MM)) * 100;
  }
  percent = Math.round(Math.min(percent, 100) * 10) / 10;
  return percent > 0 ? percent : null;
}

/** The formatting a top-level block holds itself that its element doesn't have yet. */
function directStyles(node: TiptapNode, element: Element, layout: Layout): DirectStyle[] {
  const css = layout.resolvedStyles[element.styleRef ?? targetForElement(element)] ?? {};
  const alignment = node.attrs?.textAlign;
  if ((node.type === "paragraph" || node.type === "heading") && typeof alignment === "string" && _ALIGNMENTS.has(alignment)) {
    if (alignment !== (css["text-align"] ?? "left")) return [{ elementId: element.id, property: "alignment", value: alignment, unit: null }];
  }
  if (node.type === "image" && given(node.attrs?.width)) {
    const percent = widthPercent(node.attrs?.width, layout.settings);
    if (percent === null) note(NOT_KEPT.pictureSize);
    else if (css.width !== `${percent}%`) return [{ elementId: element.id, property: "imageWidth", value: String(percent), unit: "%" }];
  }
  return [];
}

/**
 * reconcileElements, plus the element id each top-level node ended up with --
 * written back into the editor, so a new block keeps the same id from one save to
 * the next -- and, given the page's layout, the formatting the editor holds on
 * blocks themselves (to save with them) and what it holds that can't be kept.
 */
export function reconcileWithIds(tiptapContent: TiptapNode[], currentElements: Element[], layout?: Layout): Reconciled {
  notes = new Set();
  try {
    const { elements, nodeIds } = reconcile(tiptapContent, currentElements);
    const byId = new Map(elements.map((element) => [element.id, element]));
    const styles = layout
      ? tiptapContent.flatMap((node, index) => {
          const element = nodeIds[index] ? byId.get(nodeIds[index]!) : undefined;
          return element ? directStyles(node, element, layout) : [];
        })
      : [];
    return { elements, nodeIds, styles, notes: [...notes] };
  } finally {
    notes = null;
  }
}

function reconcile(tiptapContent: TiptapNode[], currentElements: Element[]): { elements: Element[]; nodeIds: (string | null)[] } {
  const byId = new Map(currentElements.map((el) => [el.id, el]));
  const end = contentEnd(tiptapContent);
  const derivedNodes = tiptapContent.slice(0, end).map((node) => deriveFromNode(node, ""));
  const owners = identityOwners(tiptapContent, derivedNodes, byId);
  const result: Element[] = [];
  const nodeIds: (string | null)[] = tiptapContent.map(() => null);

  derivedNodes.forEach((derived, index) => {
    const elementId = (tiptapContent[index].attrs?.elementId as string | undefined) ?? undefined;
    const existing = elementId && owners.get(elementId) === index ? byId.get(elementId) : undefined;
    if (existing) {
      adoptParts(derived, existing);
      result.push({ ...existing, ...derived, order: result.length });
    } else {
      result.push({
        id: crypto.randomUUID(),
        parentId: null,
        confidence: null,
        styleRef: null,
        preservedAttributes: null,
        // A new block has no original XML to copy; an existing one keeps what the
        // server says it came from (the server ignores what is sent, DOCX-028).
        sourceBlocks: null,
        sourceHash: null,
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
function identityOwners(nodes: TiptapNode[], derived: Derived[], byId: Map<string, Element>): Map<string, number> {
  const owners = new Map<string, number>();
  const bestScore = new Map<string, number>();
  derived.forEach((element, index) => {
    const id = nodes[index].attrs?.elementId as string | undefined;
    const existing = id ? byId.get(id) : undefined;
    if (!id || !existing) return;
    const score = sharedEnds(element.content, existing.content);
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
