import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import { assetUrl } from "@/services/api/assets";
import type { Element } from "@/types/document";

import { editorExtensions } from "./extensions";
import { pictureAssetIds, picturesLeftOut, removePictures } from "./leftOutPictures";

const editors: Editor[] = [];
afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

function picture(assetId: string): Element {
  return { type: "image", content: "", image: { src: "", assetId } } as unknown as Element;
}

describe("pictures a save sent that the server didn't keep (S2-131a)", () => {
  it("finds stored pictures at any depth: blocks, list items and table cells", () => {
    const elements = [
      picture("top"),
      { type: "quote", content: "", children: [picture("in-quote")] },
      { type: "list", content: "", listItems: [{ blocks: [picture("in-list")] }] },
      { type: "table", content: "", table: { rows: [{ cells: [{ blocks: [picture("in-cell")] }] }] } },
      { type: "paragraph", content: "text" },
    ] as unknown as Element[];

    expect([...pictureAssetIds(elements)].sort()).toEqual(["in-cell", "in-list", "in-quote", "top"]);
    expect([...picturesLeftOut(elements, [picture("top"), picture("in-list")])].sort()).toEqual(["in-cell", "in-quote"]);
  });

  it("takes out every picture showing them, outside the undo history, and nothing else", () => {
    const editor = new Editor({
      extensions: editorExtensions,
      content: `<p>One</p><img src="${assetUrl("gone")}"><p>Two</p><img src="${assetUrl("kept")}"><img src="${assetUrl("gone")}">`,
    });
    editors.push(editor);
    const shown = () => {
      const found: string[] = [];
      editor.state.doc.descendants((node) => {
        if (node.type.name === "image") found.push(String(node.attrs.src));
      });
      return found;
    };

    expect(removePictures(editor, new Set(["gone"]), "test")).toBe(2);
    expect(shown()).toEqual([assetUrl("kept")]);
    expect(editor.state.doc.textContent).toBe("OneTwo");
    expect(editor.can().undo()).toBe(false);
    expect(removePictures(editor, new Set(["none"]), "test")).toBe(0);
  });
});
