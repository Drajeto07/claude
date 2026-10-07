import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import { blockDoms } from "./blockDom";
import { editorExtensions } from "./extensions";

/** Each block's DOM in one walk (PERF-005): the same nodes view.nodeDOM gives, a list's items too. */

const editors: Editor[] = [];
afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

function open(html: string) {
  const editor = new Editor({ extensions: editorExtensions, content: html });
  editors.push(editor);
  return editor;
}

describe("the DOM of each block", () => {
  it("is what nodeDOM gives, for every block and every list item", () => {
    const editor = open("<h1>Title</h1><p>One</p><ul><li><p>a</p></li><li><p>b</p></li></ul><p>Two</p><hr><p>Three</p>");
    const { view } = editor;
    const blocks = blockDoms(view);
    expect(blocks.map((block) => block.node.type.name)).toEqual(["heading", "paragraph", "bulletList", "paragraph", "horizontalRule", "paragraph"]);
    for (const block of blocks) {
      expect(block.dom).toBe(view.nodeDOM(block.pos));
      for (const child of block.children()) expect(child.dom).toBe(view.nodeDOM(child.pos));
    }
    expect(blocks[2].children().map((item) => item.dom?.textContent)).toEqual(["a", "b"]);
  });

  it("falls back to nodeDOM when the view isn't as expected", () => {
    const editor = open("<p>One</p><p>Two</p>");
    const { view } = editor;
    const docView = (view as unknown as { docView: { children: unknown[] } }).docView;
    const children = docView.children;
    docView.children = children.slice(0, 1); // one block short of the document
    try {
      expect(blockDoms(view).map((block) => block.dom)).toEqual([view.nodeDOM(0), view.nodeDOM(5)]);
    } finally {
      docView.children = children;
    }
  });
});
