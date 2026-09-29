import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Document, Element, ImageContent } from "@/types/document";

import { documentToTiptapJSON } from "./documentToTiptap";
import { editorExtensions } from "./extensions";
import { reconcileWithIds } from "./tiptapToDocument";

/**
 * A Word picture in the editor (tracker DOCX-018): its type, name, size, crop, turn,
 * flips and placement come back from the editor as they went in, and the page draws
 * the picture cropped, turned and at its size.
 */

const editors: Editor[] = [];

afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

const PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

const PICTURE: ImageContent = {
  src: PNG,
  assetId: null,
  alt: "A flag",
  title: "Flag",
  mime: "image/png",
  name: "flag.png",
  widthCm: 4,
  heightCm: 2,
  crop: { left: 0.25, top: 0, right: 0, bottom: 0 },
  rotation: 90,
  flipHorizontal: true,
  flipVertical: false,
  placement: {
    wrap: "square",
    horizontalFrom: "margin",
    horizontalAlign: null,
    horizontalCm: 2,
    verticalFrom: "paragraph",
    verticalAlign: "top",
    verticalCm: null,
    distanceTopCm: 0,
    distanceBottomCm: 0,
    distanceLeftCm: 0.32,
    distanceRightCm: 0.32,
    allowOverlap: true,
    layoutInCell: true,
  },
};

function pictureElement(image: ImageContent): Element {
  return {
    id: crypto.randomUUID(),
    type: "image",
    content: "",
    inline: null,
    listItems: null,
    ordered: false,
    table: null,
    image,
    language: null,
    level: null,
    children: null,
    numbering: null,
    parentId: null,
    order: 0,
    styleRef: null,
    confidence: null,
    preservedAttributes: null,
    sourceBlocks: null,
    sourceHash: null,
    sectionBreak: null,
  } as Element;
}

function open(image: ImageContent) {
  const element = pictureElement(image);
  const document = { elements: [element], resolvedStyles: {}, settings: {} } as unknown as Document;
  const editor = new Editor({ extensions: editorExtensions, content: documentToTiptapJSON(document) });
  editors.push(editor);
  return { editor, element };
}

describe("a Word picture in the editor", () => {
  it("comes back as it went in", () => {
    const { editor, element } = open(PICTURE);

    const { elements: saved } = reconcileWithIds((editor.getJSON().content ?? []) as Record<string, unknown>[], [element]);

    expect(saved[0].image).toEqual(PICTURE);
  });

  it("is drawn cropped, turned and at its size", () => {
    const { editor } = open(PICTURE);
    const style = (editor.view.dom.querySelector("img") as HTMLElement).style;

    expect(style.width).toBe("5.3333cm"); // as if whole: 4 cm is the three quarters kept
    expect(style.clipPath).toBe("inset(0% 0% 0% 25%)");
    expect(style.transform).toBe("rotate(90deg) scale(-1, 1)");
    // Turned a quarter, the 4 by 2 cm kept takes 2 by 4: each side comes in 1 cm, the top
    // and bottom go out 1 cm -- and the 1.3333 cm cut off the left is pulled in too.
    expect([style.marginTop, style.marginRight, style.marginBottom, style.marginLeft]).toEqual(["1cm", "-1cm", "1cm", "-2.3333cm"]);
  });

  it("gives a picture turned but not cropped the room of its turned outline", () => {
    const { editor } = open({ ...PICTURE, crop: null, flipHorizontal: false });
    const style = (editor.view.dom.querySelector("img") as HTMLElement).style;

    expect([style.width, style.clipPath, style.transform, style.transformOrigin]).toEqual(["4cm", "", "rotate(90deg)", "50% 50%"]);
    expect([style.marginTop, style.marginRight, style.marginBottom, style.marginLeft]).toEqual(["1cm", "-1cm", "1cm", "-1cm"]);
  });

  it("draws an uncropped one at its own size and proportions", () => {
    const { editor } = open({ ...PICTURE, crop: null, rotation: null, flipHorizontal: false });
    const style = (editor.view.dom.querySelector("img") as HTMLElement).style;

    expect([style.width, style.aspectRatio, style.transform]).toEqual(["4cm", "2 / 1", ""]);
  });
});
