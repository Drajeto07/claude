import { describe, expect, it } from "vitest";

import type { ContentSaved, Document, Element } from "@/types/document";

import { applyContentSaved, contentPatch } from "./contentPatch";

function paragraph(id: string, text = id, order = 0): Element {
  return { id, type: "paragraph", content: text, order, inline: [{ text, marks: [] }] } as unknown as Element;
}

const list = (...elements: Element[]) => elements.map((element, order) => ({ ...element, order }));

describe("what a save sends (PERF-003)", () => {
  const saved = list(paragraph("a"), paragraph("b"), paragraph("c"));

  it("is the block that changed, and nothing else", () => {
    const typed = list(saved[0], paragraph("b", "b typed"), saved[2]);
    expect(contentPatch(typed, saved, [])).toEqual({ changed: [typed[1]], added: [], removed: [], styles: [] });
  });

  it("is a new block and where it goes, not the blocks after it that only moved down", () => {
    const first = paragraph("new");
    const later = [paragraph("x"), paragraph("y")];
    expect(contentPatch(list(first, ...saved), saved, [])!.added).toEqual([{ after: null, element: { ...first, order: 0 } }]);
    expect(contentPatch(list(saved[0], ...later, saved[1], saved[2]), saved, [])).toEqual({
      changed: [],
      added: [
        { after: "a", element: { ...later[0], order: 1 } },
        { after: "x", element: { ...later[1], order: 2 } },
      ],
      removed: [],
      styles: [],
    });
  });

  it("names the blocks removed, and carries the direct styles", () => {
    const styles = [{ elementId: "a", property: "alignment", value: "center", unit: null }] as const;
    expect(contentPatch(list(saved[0], saved[2]), saved, [...styles])).toEqual({ changed: [], added: [], removed: ["b"], styles: [...styles] });
  });

  it("is the whole document when a block moved, or most of the document changed", () => {
    expect(contentPatch(list(saved[2], saved[0], saved[1]), saved, [])).toBeNull();

    const long = list(...Array.from({ length: 60 }, (_, n) => paragraph(`p${n}`)));
    const edited = (count: number) => long.map((element, index) => (index < count ? { ...element, content: "typed" } : element));
    expect(contentPatch(edited(30), long, [])).not.toBeNull();
    expect(contentPatch(edited(31), long, [])).toBeNull();
    // A short document's patch is short anyway.
    expect(contentPatch(list(paragraph("a", "1"), paragraph("b", "2"), paragraph("c", "3")), saved, [])).not.toBeNull();
  });
});

describe("what the editor makes of the answer", () => {
  const base = {
    id: "doc-1",
    revision: 4,
    metadata: { title: "Report", updatedAt: "2026-10-01T10:00:00Z" },
    resolvedStyles: { paragraph: { "font-size": "12pt" } },
    elements: list(paragraph("a"), paragraph("b"), paragraph("c")),
  } as unknown as Document;

  it("is the document the server holds: its elements in place, in the patch's order, and what else changed", () => {
    const stored = { ...paragraph("b", "b typed"), order: 2, styleRef: "paragraph" };
    const added = { ...paragraph("x"), order: 1, styleRef: "paragraph" };
    const answer = { revision: 5, changed: [added, stored], order: null, fields: { metadata: { title: "Report", updatedAt: "2026-10-01T10:01:00Z" } } } as unknown as ContentSaved;

    const merged = applyContentSaved(base, ["a", "x", "b", "c"], answer);

    expect(merged.revision).toBe(5);
    expect(merged.metadata.updatedAt).toBe("2026-10-01T10:01:00Z");
    expect(merged.resolvedStyles).toBe(base.resolvedStyles);
    expect(merged.elements.map((element) => [element.id, element.order, element.content])).toEqual([
      ["a", 0, "a"],
      ["x", 1, "x"],
      ["b", 2, "b typed"],
      ["c", 3, "c"],
    ]);
    // An unchanged block in its old place is the same object; one moved down only gets its new order.
    expect(merged.elements[0]).toBe(base.elements[0]);
    expect(merged.elements[3]).toEqual({ ...base.elements[2], order: 3 });
  });

  it("follows the server's order when it gives one, and refuses an answer that doesn't fit", () => {
    const answer = { revision: 5, changed: [], order: ["c", "a"], fields: {} } as unknown as ContentSaved;
    expect(applyContentSaved(base, ["a", "b", "c"], answer).elements.map((element) => element.id)).toEqual(["c", "a"]);
    expect(() => applyContentSaved(base, ["a", "q"], { ...answer, order: null })).toThrow(/doesn't know/);
  });
});
