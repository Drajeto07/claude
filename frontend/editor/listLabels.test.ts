import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Document, Element, ListNumbering } from "@/types/document";

import { documentToTiptapJSON } from "./documentToTiptap";
import { editorExtensions } from "./extensions";
import { Counters, formatListNumber, levelLabel } from "./listLabels";

/**
 * Each list item's label on the pages (tracker DOCX-016), as Word and both exports
 * number it -- the backend's app/formatting/list_numbering.py, mirrored.
 */

const editors: Editor[] = [];

afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

const LEVEL = { start: 1, indentCm: null, hangingCm: null, legal: false, restartAfter: null, suffix: "tab" as const };

function list(items: [string, number][], numbering: ListNumbering | null, ordered = true): Element {
  return {
    id: crypto.randomUUID(),
    type: "list",
    content: items.map(([text]) => text).join("\n"),
    inline: null,
    listItems: items.map(([text, level]) => ({ id: crypto.randomUUID(), inline: [{ text, marks: [] }], level, checked: null, blocks: null })),
    ordered,
    table: null,
    image: null,
    language: null,
    level: null,
    children: null,
    numbering,
    parentId: null,
    order: 0,
    styleRef: null,
    confidence: null,
    preservedAttributes: null,
    sourceBlocks: null,
    sourceHash: null,
    layout: null,
    sectionBreak: null,
    numbered: null,
  } as Element;
}

function labels(element: Element): string[] {
  const document = { elements: [element], resolvedStyles: {}, settings: {} } as unknown as Document;
  const editor = new Editor({ extensions: editorExtensions, content: documentToTiptapJSON(document) });
  editors.push(editor);
  return [...editor.view.dom.querySelectorAll("li")].map((item) => item.getAttribute("data-label") ?? "(none)");
}

describe("list labels on the pages", () => {
  it("numbers each level with its own label", () => {
    const articles: ListNumbering = {
      start: 1,
      format: "decimal",
      levels: [
        { ...LEVEL, format: "decimal", text: "Чл. %1.", indentCm: 1.27, hangingCm: 1.27 },
        { ...LEVEL, format: "russianLower", text: "%2)" },
        { ...LEVEL, format: "decimal", text: "%1.%2.%3.", legal: true },
      ],
    };

    expect(labels(list([["Scope", 0], ["point", 1], ["clause", 2], ["other", 1], ["Terms", 0]], articles))).toEqual([
      "Чл. 1.",
      "а)",
      "1.1.1.",
      "б)",
      "Чл. 2.",
    ]);
  });

  it("counts deeper levels 1., a., i. and bullets •, ◦, ▪ where a list has no levels of its own", () => {
    expect(labels(list([["one", 0], ["deeper", 1], ["deepest", 2], ["two", 0], ["again", 1]], null))).toEqual(["1.", "a.", "i.", "2.", "a."]);
    expect(labels(list([["dot", 0], ["circle", 1], ["square", 2]], null, false))).toEqual(["•", "◦", "▪"]);
    expect(labels(list([["fifth", 0], ["sixth", 0]], { start: 5, format: "upperRoman", levels: null }))).toEqual(["V.", "VI."]);
  });

  it("draws a list's own bullets", () => {
    const bullets: ListNumbering = { start: 1, format: "decimal", levels: [{ ...LEVEL, format: "bullet", text: "➢" }, { ...LEVEL, format: "bullet", text: "–" }] };

    expect(labels(list([["arrow", 0], ["dash", 1]], bullets, false))).toEqual(["➢", "–"]);
  });

  it("counts as Word counts", () => {
    expect([1, 9, 10, 28, 29].map((value) => formatListNumber(value, "russianLower"))).toEqual(["а", "и", "к", "я", "аа"]);
    expect([formatListNumber(7, "decimalZero"), formatListNumber(12, "decimalZero"), formatListNumber(27, "lowerLetter")]).toEqual(["07", "12", "aa"]);
    const counters = new Counters([1, 1, 1], [null, null, 1]);
    expect([counters.advance(0), counters.advance(1), counters.advance(2), counters.advance(1), counters.advance(2)]).toEqual([[1], [1, 1], [1, 1, 1], [1, 2], [1, 2, 2]]);
    expect([counters.advance(0), counters.advance(2)]).toEqual([[2], [2, 0, 1]]); // a skipped level shows 0
    expect(levelLabel("%1.%2.", [2, 3], ["upperRoman", "lowerLetter"])).toBe("II.c.");
    expect(levelLabel("%1.%2.", [2, 3], ["upperRoman", "lowerLetter"], true)).toBe("2.3.");
  });
});
