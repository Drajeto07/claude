import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Document, Element } from "@/types/document";

import { documentToTiptapJSON } from "./documentToTiptap";
import { editorExtensions } from "./extensions";
import { textBoxStyle } from "./textBox";
import { reconcileWithIds } from "./tiptapToDocument";

/**
 * A Word text box in the editor (tracker DOCX-019A): drawn as a box with its width, outline,
 * fill and insets, holding its own blocks, and saved back as it came.
 */

const editors: Editor[] = [];
afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

function block(type: string, content: string, extra: Partial<Element> = {}): Element {
  return {
    id: crypto.randomUUID(), type, content, inline: content ? [{ text: content, marks: [] }] : null, listItems: null, ordered: false,
    table: null, image: null, textBox: null, language: null, level: null, children: null, numbering: null, parentId: null, order: 0,
    styleRef: null, confidence: null, preservedAttributes: null, sourceBlocks: null, sourceHash: null, sectionBreak: null, numbered: null,
    layout: null, ...extra,
  } as Element;
}

const LOOK = {
  widthCm: 5, heightCm: 2, border: "solid 1pt #C00000", fill: "#FFF2CC",
  insets: { topCm: 0.1, bottomCm: 0.1, leftCm: 0.2, rightCm: 0.2 }, name: "Note", placement: null,
};

function textBox(): Element {
  const children = [block("paragraph", "A note in a box."), block("paragraph", "Its second line.")];
  return block("text_box", "A note in a box.\nIts second line.", { inline: null, children, textBox: LOOK });
}

function open(elements: Element[]) {
  const document = { elements, resolvedStyles: {}, settings: {} } as unknown as Document;
  const editor = new Editor({ extensions: editorExtensions, content: documentToTiptapJSON(document) });
  editors.push(editor);
  return editor;
}

describe("a text box in the editor", () => {
  it("is drawn as a box holding its own paragraphs", () => {
    const editor = open([block("paragraph", "Before it."), textBox()]);
    const box = editor.view.dom.querySelector<HTMLElement>('div[data-type="text-box"]')!;
    expect(box).not.toBeNull();
    expect([...box.querySelectorAll("p")].map((paragraph) => paragraph.textContent)).toEqual(["A note in a box.", "Its second line."]);
    expect([box.style.width, box.style.backgroundColor]).toEqual(["5cm", "rgb(255, 242, 204)"]);
  });

  it("comes back from the editor as it went in", () => {
    const element = textBox();
    const editor = open([element]);
    const { elements: saved } = reconcileWithIds((editor.getJSON().content ?? []) as Record<string, unknown>[], [element]);
    expect(saved[0].type).toBe("text_box");
    expect(saved[0].textBox).toEqual(LOOK);
    expect(saved[0].children?.map((child) => child.content)).toEqual(["A note in a box.", "Its second line."]);
    expect(saved[0].content).toBe("A note in a box.\nIts second line.");
  });

  it("is outlined as Word draws a box with no outline of its own, and not at all with none", () => {
    expect(textBoxStyle(null)).toContain("border:0.5pt solid #000000");
    expect(textBoxStyle({ ...LOOK, border: "none" })).toContain("border:none");
  });
});
