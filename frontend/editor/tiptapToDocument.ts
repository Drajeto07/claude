import { assetIdFromUrl } from "@/services/api";
import type { Element, ElementType, ImageContent, InlineRun, ListItem, Mark, MarkType, TableCell, TableContent, TableRow } from "@/types/document";

type TiptapNode = {
  type?: string;
  text?: string;
  attrs?: Record<string, unknown>;
  content?: TiptapNode[];
  marks?: { type: string; attrs?: Record<string, unknown> }[];
};

const _MARK_TYPES: MarkType[] = ["bold", "italic", "underline", "strike", "code", "link"];

function marksFromTiptap(marks: TiptapNode["marks"]): Mark[] {
  if (!marks) return [];
  const result: Mark[] = [];
  for (const mark of marks) {
    if (!(_MARK_TYPES as string[]).includes(mark.type)) continue;
    result.push({ type: mark.type as MarkType, href: mark.type === "link" ? ((mark.attrs?.href as string) ?? null) : null });
  }
  return result;
}

function inlineFromContent(content: TiptapNode[] | undefined): InlineRun[] {
  return (content ?? [])
    .filter((node) => node.type === "text" && typeof node.text === "string")
    .map((node) => ({ text: node.text as string, marks: marksFromTiptap(node.marks) }));
}

function plainText(inline: InlineRun[]): string {
  return inline.map((run) => run.text).join("");
}

// Mirrors documentToTiptap.ts's checklistAwareInline in reverse -- a
// checklist item is stored as a plain text glyph prefix (no TaskItem
// extension installed this project), so reconciling one back out means
// recognizing and stripping that same prefix.
function stripChecklistGlyph(inline: InlineRun[]): { inline: InlineRun[]; checked: boolean | null } {
  const first = inline[0];
  if (first && first.marks.length === 0) {
    if (first.text.startsWith("☑ ")) return { inline: [{ ...first, text: first.text.slice(2) }, ...inline.slice(1)], checked: true };
    if (first.text.startsWith("☐ ")) return { inline: [{ ...first, text: first.text.slice(2) }, ...inline.slice(1)], checked: false };
  }
  return { inline, checked: null };
}

function flattenListItems(content: TiptapNode[] | undefined, level: number): ListItem[] {
  const items: ListItem[] = [];
  for (const listItem of content ?? []) {
    const children = listItem.content ?? [];
    const paragraph = children.find((child) => child.type === "paragraph");
    const nestedList = children.find((child) => child.type === "bulletList" || child.type === "orderedList");
    const { inline, checked } = stripChecklistGlyph(inlineFromContent(paragraph?.content));
    items.push({ id: crypto.randomUUID(), inline, level, checked });
    if (nestedList) items.push(...flattenListItems(nestedList.content, level + 1));
  }
  return items;
}

function tableContentFromNode(node: TiptapNode): TableContent {
  const rows: TableRow[] = (node.content ?? []).map((row) => {
    const cells: TableCell[] = (row.content ?? []).map((cell) => ({
      id: crypto.randomUUID(),
      inline: inlineFromContent(cell.content?.[0]?.content),
      header: cell.type === "tableHeader",
      colspan: 1,
      rowspan: 1,
    }));
    return { id: crypto.randomUUID(), cells };
  });
  const hasHeaderRow = rows.length > 0 && rows[0].cells.every((cell) => cell.header);
  return { rows, hasHeaderRow, alignments: null };
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

// The inverse of documentToTiptap.ts's elementToNode -- given a live Tiptap
// node, derives the Element fields that come from its editable content.
// Returns null for a node type this reconciliation doesn't (yet) reconstruct
// from scratch -- deliberately scoped to top-level block content/structure
// (see the plan's Stage 0 note); deep in-place list/table restructuring via
// direct typing is a known, flagged limitation, not a silent gap.
function deriveFromNode(node: TiptapNode): Derived | null {
  switch (node.type) {
    case "heading": {
      const inline = inlineFromContent(node.content);
      return { type: "heading", content: plainText(inline), inline, listItems: null, ordered: false, table: null, image: null, language: null, level: (node.attrs?.level as number) ?? 1 };
    }
    case "paragraph": {
      const inline = inlineFromContent(node.content);
      return { type: "paragraph", content: plainText(inline), inline, listItems: null, ordered: false, table: null, image: null, language: null, level: null };
    }
    case "caption": {
      const inline = inlineFromContent(node.content);
      return { type: "caption", content: plainText(inline), inline, listItems: null, ordered: false, table: null, image: null, language: null, level: null };
    }
    case "blockquote": {
      const inline = inlineFromContent(node.content?.[0]?.content);
      return { type: "quote", content: plainText(inline), inline, listItems: null, ordered: false, table: null, image: null, language: null, level: null };
    }
    case "codeBlock": {
      const text = (node.content ?? []).map((child) => child.text ?? "").join("");
      return { type: "code_block", content: text, inline: null, listItems: null, ordered: false, table: null, image: null, language: (node.attrs?.language as string) ?? null, level: null };
    }
    case "bulletList":
    case "orderedList": {
      const listItems = flattenListItems(node.content, 0);
      return {
        type: "list",
        content: listItems.map((item) => plainText(item.inline)).join("\n"),
        inline: null,
        listItems,
        ordered: node.type === "orderedList",
        table: null,
        image: null,
        language: null,
        level: null,
      };
    }
    case "table": {
      const table = tableContentFromNode(node);
      return {
        type: "table",
        content: table.rows.map((row) => row.cells.map((cell) => plainText(cell.inline)).join("\t")).join("\n"),
        inline: null,
        listItems: null,
        ordered: false,
        table,
        image: null,
        language: null,
        level: null,
      };
    }
    case "image":
      return { type: "image", content: "", inline: null, listItems: null, ordered: false, table: null, image: imageContentFromNode(node), language: null, level: null };
    case "pageBreak":
      return { type: "page_break", content: "", inline: null, listItems: null, ordered: false, table: null, image: null, language: null, level: null };
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
 * DocumentEditor already renders in.
 */
export function reconcileElements(tiptapContent: TiptapNode[], currentElements: Element[]): Element[] {
  const byId = new Map(currentElements.map((el) => [el.id, el]));
  const result: Element[] = [];

  for (const node of tiptapContent) {
    const elementId = (node.attrs?.elementId as string | undefined) ?? undefined;
    const existing = elementId ? byId.get(elementId) : undefined;
    const derived = deriveFromNode(node);
    if (!derived) continue; // unrecognized node type -- leave whatever existed there out rather than guess

    if (existing) {
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
  }
  return result;
}
