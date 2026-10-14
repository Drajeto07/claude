import type { Element } from "@/types/document";

/**
 * The structure review's edits (S2-020): what a block is (Heading 1-3 or body text) and where a section sits.
 * Pure functions over the document's top-level elements -- nothing here touches a block's words, its inline
 * formatting or what the import preserved; the result is saved once with PUT /content.
 */

export type BlockKind = "h1" | "h2" | "h3" | "body";

export const BLOCK_KINDS: readonly BlockKind[] = ["h1", "h2", "h3", "body"];

/** Only headings and paragraphs can change kind; lists, tables, pictures and the rest stay as they are. */
export function canChangeKind(element: Element): boolean {
  return element.type === "heading" || element.type === "paragraph";
}

export function kindOf(element: Element): BlockKind | null {
  if (element.type === "paragraph") return "body";
  if (element.type !== "heading") return null;
  const level = Math.min(Math.max(element.level ?? 1, 1), 3);
  return `h${level}` as BlockKind;
}

/** A block as another kind. A Word style that named the old kind goes with it (it would say the wrong
 * thing), and the user's decision counts as certain. */
export function withKind(elements: Element[], id: string, kind: BlockKind): Element[] {
  return elements.map((element) => {
    if (element.id !== id || !canChangeKind(element) || kindOf(element) === kind) return element;
    const changed: Element = { ...element, styleRef: null, confidence: 1 };
    if (kind === "body") return { ...changed, type: "paragraph", level: null, numbered: null };
    return { ...changed, type: "heading", level: Number(kind.slice(1)) };
  });
}

/** Where a heading's section ends: the next heading of the same or a higher level (or the end). */
function sectionEnd(elements: Element[], start: number): number {
  const level = elements[start].level ?? 1;
  let end = start + 1;
  while (end < elements.length && !(elements[end].type === "heading" && (elements[end].level ?? 1) <= level)) end += 1;
  return end;
}

/** The section before or after a heading's own at the same level, if there is one to swap with. */
function neighbour(elements: Element[], start: number, direction: "up" | "down"): [number, number] | null {
  const level = elements[start].level ?? 1;
  if (direction === "down") {
    const end = sectionEnd(elements, start);
    const next = elements[end];
    if (!next || next.type !== "heading" || (next.level ?? 1) !== level) return null;
    return [end, sectionEnd(elements, end)];
  }
  for (let index = start - 1; index >= 0; index -= 1) {
    const element = elements[index];
    if (element.type !== "heading") continue;
    const other = element.level ?? 1;
    if (other < level) return null;  // the parent section starts here: nothing above to swap with
    if (other === level) return [index, start];
  }
  return null;
}

export function canMoveSection(elements: Element[], headingId: string, direction: "up" | "down"): boolean {
  const start = elements.findIndex((element) => element.id === headingId);
  return start >= 0 && elements[start].type === "heading" && neighbour(elements, start, direction) !== null;
}

/** A heading's whole section (it and everything under it) swapped with the neighbouring section of the
 * same level. Nothing is lost or duplicated: the same blocks, another order. */
export function moveSection(elements: Element[], headingId: string, direction: "up" | "down"): Element[] {
  const start = elements.findIndex((element) => element.id === headingId);
  if (start < 0 || elements[start].type !== "heading") return elements;
  const other = neighbour(elements, start, direction);
  if (!other) return elements;
  const end = sectionEnd(elements, start);
  const [first, second] = direction === "up" ? [other, [start, end] as [number, number]] : [[start, end] as [number, number], other];
  const reordered = [
    ...elements.slice(0, first[0]),
    ...elements.slice(second[0], second[1]),
    ...elements.slice(first[0], first[1]),
    ...elements.slice(second[1]),
  ];
  return reordered.map((element, order) => (element.order === order ? element : { ...element, order }));
}

/** Whether the review changed anything worth saving (kind, level or order of a block). */
export function structureChanged(before: Element[], after: Element[]): boolean {
  if (before.length !== after.length) return true;
  return after.some((element, index) => {
    const original = before[index];
    return original.id !== element.id || original.type !== element.type || (original.level ?? null) !== (element.level ?? null);
  });
}
