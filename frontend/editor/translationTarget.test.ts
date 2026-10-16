import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import { editorExtensions } from "./extensions";
import { translationTarget } from "./translationTarget";

const editors: Editor[] = [];
afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

function editorWith(): Editor {
  const editor = new Editor({
    extensions: editorExtensions,
    content: {
      type: "doc",
      content: [
        { type: "heading", attrs: { level: 1, elementId: "h1" }, content: [{ type: "text", text: "Dosage" }] },
        { type: "paragraph", attrs: { elementId: "p1" }, content: [{ type: "text", text: "Take " }, { type: "text", text: "5 mg", marks: [{ type: "bold" }] }, { type: "text", text: " daily." }] },
        { type: "paragraph", attrs: { elementId: "p2" }, content: [{ type: "text", text: "Keep it dry." }] },
      ],
    },
  });
  editors.push(editor);
  return editor;
}

/** The position of the `index`-th character of the block's text (blocks are counted from 0). */
function at(editor: Editor, block: number, index: number): number {
  let position = 0;
  editor.state.doc.forEach((node, offset, i) => {
    if (i === block) position = offset + 1 + index;
  });
  return position;
}

describe("what Translate selection translates", () => {
  it("is the cursor's block when nothing is selected", () => {
    const editor = editorWith();
    editor.commands.setTextSelection(at(editor, 1, 2));
    expect(translationTarget(editor)).toEqual({ elementIds: ["p1"], selection: null });
  });

  it("is every block the selection touches", () => {
    const editor = editorWith();
    editor.commands.setTextSelection({ from: at(editor, 0, 1), to: at(editor, 2, 3) });
    expect(translationTarget(editor)).toEqual({ elementIds: ["h1", "p1", "p2"], selection: null });
  });

  it("is part of one block's text when only part is selected, counted across its runs", () => {
    const editor = editorWith();
    editor.commands.setTextSelection({ from: at(editor, 1, 5), to: at(editor, 1, 15) }); // "5 mg daily"
    expect(translationTarget(editor)).toEqual({ elementIds: ["p1"], selection: { start: 5, end: 15 } });
  });

  it("is the whole block when all of its text is selected", () => {
    const editor = editorWith();
    editor.commands.setTextSelection({ from: at(editor, 2, 0), to: at(editor, 2, 12) });
    expect(translationTarget(editor)).toEqual({ elementIds: ["p2"], selection: null });
  });
});
