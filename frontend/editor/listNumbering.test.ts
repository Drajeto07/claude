import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Document, Element, ListNumbering } from "@/types/document";

import { documentToTiptapJSON } from "./documentToTiptap";
import { editorExtensions } from "./extensions";
import { reconcileWithIds } from "./tiptapToDocument";

/**
 * A list's own numbering from Word (tracker DOCX-016) -- each level's format, label,
 * start and indent, a format the HTML list types can't say, its bullets -- goes
 * through the editor and back unchanged, so a save never drops it.
 */

const editors: Editor[] = [];

afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

const LEVEL = { start: 1, indentCm: 1.27, hangingCm: 0.63, legal: false, restartAfter: null, suffix: "tab" as const };

function list(numbering: ListNumbering | null, ordered: boolean, order: number): Element {
  return {
    id: crypto.randomUUID(),
    type: "list",
    content: "One\nTwo",
    inline: null,
    listItems: [
      { id: crypto.randomUUID(), inline: [{ text: "One", marks: [] }], level: 0, checked: null, blocks: null, preservedAttributes: null },
      { id: crypto.randomUUID(), inline: [{ text: "Two", marks: [] }], level: 1, checked: null, blocks: null, preservedAttributes: null },
    ],
    ordered,
    table: null,
    image: null,
    language: null,
    level: null,
    children: null,
    numbering,
    parentId: null,
    order,
    styleRef: null,
    confidence: null,
    preservedAttributes: null,
    sourceBlocks: null,
    sourceHash: null,
    layout: null,
    sectionBreak: null,
    numbered: null,
    textBox: null,
  } as Element;
}

describe("a list's own numbering in the editor", () => {
  it("comes back as it was: levels, a format HTML lists can't say, bullets", () => {
    const articles: ListNumbering = {
      start: 3,
      format: "decimal",
      levels: [
        { ...LEVEL, format: "decimal", text: "Чл. %1." },
        { ...LEVEL, format: "russianLower", text: "%2)", legal: true, restartAfter: 1, suffix: "space" },
      ],
    };
    const padded: ListNumbering = { start: 1, format: "decimalZero", levels: null };
    const bullets: ListNumbering = { start: 1, format: "decimal", levels: [{ ...LEVEL, format: "bullet", text: "➢" }] };
    const elements = [list(articles, true, 0), list(padded, true, 1), list(bullets, false, 2), list(null, true, 3)];
    const document = { elements, resolvedStyles: {}, settings: {} } as unknown as Document;
    const editor = new Editor({ extensions: editorExtensions, content: documentToTiptapJSON(document) });
    editors.push(editor);

    const { elements: saved } = reconcileWithIds((editor.getJSON().content ?? []) as Record<string, unknown>[], elements);

    expect(saved.map((element) => element.numbering)).toEqual([articles, padded, bullets, null]);
    expect(saved.map((element) => element.listItems?.map((item) => item.level))).toEqual(Array(4).fill([0, 1]));
  });

  it("gives a list made here none of its own", () => {
    const editor = new Editor({ extensions: editorExtensions, content: "<ol><li><p>One</p></li></ol><ul><li><p>Dot</p></li></ul>" });
    editors.push(editor);

    const { elements: saved } = reconcileWithIds((editor.getJSON().content ?? []) as Record<string, unknown>[], []);

    expect(saved.map((element) => element.numbering)).toEqual([null, null]);
  });
});
