import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import type { HeadingNumbering } from "@/types/document";

import { editorExtensions } from "./extensions";
import { HeadingNumbers, setHeadingNumbering } from "./headingNumbers";
import { reconcileWithIds } from "./tiptapToDocument";

/**
 * A document's heading numbers on the pages (tracker DOCX-016A): counted over its
 * headings in order, as Word and the exports count them (list_numbering.heading_labels),
 * so a heading moved or added here is numbered where it is; one Word doesn't number
 * keeps not being numbered, through a save too.
 */

const editors: Editor[] = [];

afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

const LEVEL = { start: 1, indentCm: null, hangingCm: null, legal: false, restartAfter: null, suffix: "tab" as const };
const OUTLINE: HeadingNumbering = {
  levels: [
    { ...LEVEL, format: "decimal", text: "%1" },
    { ...LEVEL, format: "decimal", text: "%1.%2" },
  ],
  sourceNumId: null,
};

function editorWith(content: string, numbering: HeadingNumbering | null = OUTLINE): Editor {
  const editor = new Editor({ extensions: [...editorExtensions, HeadingNumbers], content });
  editors.push(editor);
  setHeadingNumbering(editor, numbering);
  return editor;
}

function numbers(editor: Editor): (string | null)[] {
  return Array.from(editor.view.dom.querySelectorAll("h1, h2, h3")).map((heading) => heading.getAttribute("data-number"));
}

describe("heading numbers", () => {
  it("count the headings as Word does, each level under the one above", () => {
    const editor = editorWith("<h1>Introduction</h1><h2>Scope</h2><h2>Aims</h2><p>Text</p><h1>Method</h1><h2>Sample</h2>");

    expect(numbers(editor)).toEqual(["1", "1.1", "1.2", "2", "2.1"]);
  });

  it("follow a heading moved or added here", () => {
    const editor = editorWith("<h1>Introduction</h1><h1>Method</h1>");

    editor.commands.setContent("<h1>Method</h1><h1>Introduction</h1><h2>New here</h2>");

    expect(numbers(editor)).toEqual(["1", "2", "2.1"]);
  });

  it("leave out a heading Word doesn't number, and count on without it", () => {
    const editor = editorWith("<h1>Introduction</h1><h1>Method</h1>");
    editor.commands.setContent({
      type: "doc",
      content: [
        { type: "heading", attrs: { level: 1, numbered: false }, content: [{ type: "text", text: "Contents" }] },
        { type: "heading", attrs: { level: 1 }, content: [{ type: "text", text: "Introduction" }] },
      ],
    });

    expect(numbers(editor)).toEqual([null, "1"]);
    const { elements } = reconcileWithIds((editor.getJSON().content ?? []) as Record<string, unknown>[], []);
    expect(elements.map((element) => element.numbered)).toEqual([false, null]); // kept through a save
  });

  it("show a level's own label and format", () => {
    const chapters: HeadingNumbering = { levels: [{ ...LEVEL, format: "upperRoman", text: "Глава %1", start: 3 }], sourceNumId: null };
    const editor = editorWith("<h1>Начало</h1><h1>Край</h1><h2>Unnumbered level</h2>", chapters);

    expect(numbers(editor)).toEqual(["Глава III", "Глава IV", null]);
  });

  it("are none where the document's headings aren't numbered", () => {
    expect(numbers(editorWith("<h1>Introduction</h1><h2>Scope</h2>", null))).toEqual([null, null]);
  });
});
