import { describe, expect, it } from "vitest";

import type { Element } from "@/types/document";

import { canMoveSection, kindOf, moveSection, structureChanged, withKind } from "./structureEdits";

let order = 0;
function block(id: string, type: Element["type"], level: number | null = null, extra: Partial<Element> = {}): Element {
  return { id, type, content: id, level, order: order++, ...extra } as Element;
}

// Intro / A (a1, A.1 (a11)) / B (b1) / C
function sample(): Element[] {
  order = 0;
  return [
    block("intro", "paragraph"),
    block("A", "heading", 1),
    block("a1", "paragraph"),
    block("A.1", "heading", 2),
    block("a11", "list"),
    block("B", "heading", 1),
    block("b1", "paragraph"),
    block("C", "heading", 1),
  ];
}

const ids = (elements: Element[]) => elements.map((element) => element.id);

describe("what a block is", () => {
  it("a paragraph becomes a heading of the chosen level, the user's choice counted as certain", () => {
    const [changed] = withKind(sample(), "intro", "h2");
    expect(changed).toMatchObject({ type: "heading", level: 2, confidence: 1, content: "intro" });
  });

  it("a heading becomes body text: no level, no heading numbering, no Word heading style", () => {
    const elements = sample();
    elements[1] = { ...elements[1], styleRef: "Heading1", numbered: false, inline: [{ text: "A", marks: [] }] } as Element;
    const changed = withKind(elements, "A", "body")[1];
    expect(changed).toMatchObject({ type: "paragraph", level: null, numbered: null, styleRef: null });
    expect(changed.inline).toEqual(elements[1].inline);  // the words and their marks stay
  });

  it("lists, tables and pictures are not reclassified", () => {
    const elements = sample();
    expect(withKind(elements, "a11", "h1")[4]).toBe(elements[4]);
    expect(kindOf(elements[4])).toBeNull();
  });

  it("choosing what it already is changes nothing", () => {
    const elements = sample();
    expect(withKind(elements, "A", "h1")[1]).toBe(elements[1]);
  });
});

describe("moving a section", () => {
  it("down: the heading and everything under it swap with the next section of its level", () => {
    const moved = moveSection(sample(), "A", "down");
    expect(ids(moved)).toEqual(["intro", "B", "b1", "A", "a1", "A.1", "a11", "C"]);
    expect(moved.map((element) => element.order)).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
  });

  it("up: the same, the other way", () => {
    expect(ids(moveSection(sample(), "C", "up"))).toEqual(["intro", "A", "a1", "A.1", "a11", "C", "B", "b1"]);
  });

  it("a subsection stays inside its parent: nothing to swap with at the edges", () => {
    const elements = sample();
    expect(canMoveSection(elements, "A.1", "up")).toBe(false);
    expect(canMoveSection(elements, "A.1", "down")).toBe(false);
    expect(moveSection(elements, "A.1", "up")).toBe(elements);
  });

  it("the first and the last section can't move further", () => {
    const elements = sample();
    expect(canMoveSection(elements, "A", "up")).toBe(false);
    expect(canMoveSection(elements, "C", "down")).toBe(false);
    expect(canMoveSection(elements, "B", "up")).toBe(true);
  });

  it("no block is lost or doubled", () => {
    const elements = sample();
    const moved = moveSection(moveSection(elements, "B", "up"), "C", "up");
    expect([...ids(moved)].sort()).toEqual([...ids(elements)].sort());
  });
});

describe("whether there is anything to save", () => {
  it("only a change of kind, level or order counts", () => {
    const elements = sample();
    expect(structureChanged(elements, elements)).toBe(false);
    expect(structureChanged(elements, withKind(elements, "A", "h2"))).toBe(true);
    expect(structureChanged(elements, moveSection(elements, "B", "up"))).toBe(true);
  });
});
