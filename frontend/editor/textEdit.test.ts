import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import { editorExtensions } from "./extensions";
import { layoutDelay, noteTyping, onlyTextChanged, TYPING_PAUSE_MS } from "./textEdit";

/**
 * Typing told apart from changing the blocks (tracker PERF-005): the plugins that draw from the
 * blocks keep their decorations, only moved, and the page layout waits for a pause.
 */

const editors: Editor[] = [];
afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

function open(html: string) {
  const editor = new Editor({ extensions: editorExtensions, content: html });
  editors.push(editor);
  return editor;
}

describe("only text changed", () => {
  it("is typing, deleting and restyling text inside a paragraph", () => {
    const { state } = open("<p>Hello world</p><p>Second</p>");
    expect(onlyTextChanged(state.tr.insertText("X", 3))).toBe(true);
    expect(onlyTextChanged(state.tr.delete(2, 5))).toBe(true);
    expect(onlyTextChanged(state.tr.addMark(1, 6, state.schema.marks.bold.create()))).toBe(true);
  });

  it("is not a block made, joined or removed, a picture in, a selection moved", () => {
    const { state } = open('<p>Hello<br>world</p><p>Second</p><p><img src="data:image/png;base64,iVBORw0KGgo="></p>');
    expect(onlyTextChanged(state.tr.split(3))).toBe(false); // Enter
    const end = state.doc.child(0).nodeSize;
    expect(onlyTextChanged(state.tr.delete(end - 1, end + 1))).toBe(false); // two paragraphs joined
    expect(onlyTextChanged(state.tr.delete(4, 8))).toBe(false); // across the line break
    expect(onlyTextChanged(state.tr.insert(2, state.schema.nodes.hardBreak.create()))).toBe(false);
    expect(onlyTextChanged(state.tr.setSelection(state.selection))).toBe(false); // nothing changed
  });

  it("keeps a list's labels moved along while typing, and counts again once an item is added", () => {
    const editor = open("<ol><li><p>one</p></li><li><p>two</p></li></ol>");
    const labels = () => [...editor.view.dom.querySelectorAll("li")].map((item) => item.getAttribute("data-label"));
    const before = labels();
    editor.view.dispatch(editor.state.tr.insertText("!", 5));
    expect(labels()).toEqual(before);
    editor.commands.setTextSelection(6);
    editor.commands.splitListItem("listItem");
    expect(labels()).toHaveLength(3);
    expect(new Set(labels()).size).toBe(3); // each its own number
  });

  it("makes the page layout wait for a pause in the typing", () => {
    const editor = open("<p>Hello</p>");
    const typing = editor.state.tr.insertText("!", 2);
    const typed = editor.state.apply(typing);
    noteTyping(typing, typed);
    expect(layoutDelay(typed, 30)).toBe(TYPING_PAUSE_MS);
    const split = editor.state.tr.split(2);
    expect(layoutDelay(editor.state.apply(split), 30)).toBe(30);
  });
});
