import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Document, Element, ImageContent } from "@/types/document";

import { documentToTiptapJSON } from "./documentToTiptap";
import { getSelectedElementId } from "./elementId";
import { editorExtensions } from "./extensions";
import { cropped, flipped, pictureAt, turned, uncropped, updatePicture, withRotation } from "./pictureEdit";
import { NO_PICTURE } from "./pictureLook";
import { reconcileWithIds } from "./tiptapToDocument";

/**
 * Cropping, turning and flipping a picture in the editor (DOCX-018B): each change is the
 * picture's own, drawn on the page and saved with the document for the exports to follow.
 */

const editors: Editor[] = [];
afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

const PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
const WORD_PICTURE: ImageContent = {
  src: PNG,
  assetId: null,
  alt: "A flag",
  title: null,
  mime: "image/png",
  name: "flag.png",
  widthCm: 4,
  heightCm: 2,
  crop: null,
  rotation: null,
  flipHorizontal: false,
  flipVertical: false,
  placement: null,
};

function open(image: ImageContent) {
  const element = {
    id: crypto.randomUUID(),
    type: "image",
    content: "",
    image,
    order: 0,
    styleRef: null,
  } as unknown as Element;
  const document = { elements: [element], resolvedStyles: {}, settings: {} } as unknown as Document;
  const editor = new Editor({ extensions: editorExtensions, content: documentToTiptapJSON(document) });
  editors.push(editor);
  return { editor, element };
}

describe("cropping, turning and flipping a picture", () => {
  it("turns by quarters either way, to any angle, and no turn at all is none", () => {
    expect(turned(null, 90).rotation).toBe(90);
    expect(turned({ ...NO_PICTURE, rotation: 90 }, -90).rotation).toBeNull();
    expect(turned({ ...NO_PICTURE, rotation: 15 }, -90).rotation).toBe(285);
    expect(withRotation(null, 725).rotation).toBe(5);
    expect(withRotation(null, -30).rotation).toBe(330);
  });

  it("flips each way, and back", () => {
    const once = flipped(null, "horizontal");
    expect([once.flipHorizontal, once.flipVertical]).toEqual([true, false]);
    expect(flipped(once, "horizontal").flipHorizontal).toBe(false);
    expect(flipped(once, "vertical").flipVertical).toBe(true);
  });

  it("crops a side, never leaving less than a tenth with the side opposite, and no crop is none", () => {
    const left = cropped(null, "left", 25);
    expect(left.crop).toEqual({ left: 0.25, top: 0, right: 0, bottom: 0 });
    expect(cropped(left, "right", 80).crop?.right).toBe(0.65); // 25 + 65 = 90
    expect(cropped(left, "top", -5).crop?.top).toBe(0);
    expect(cropped(left, "left", 0).crop).toBeNull();
    const back = uncropped({ ...left, rotation: 90, flipVertical: true, widthCm: 4 });
    expect([back.crop, back.rotation, back.flipVertical, back.widthCm]).toEqual([null, null, false, 4]);
  });

  it("changes the picture on the page and in what is saved", () => {
    const { editor, element } = open(WORD_PICTURE);

    updatePicture(editor, element.id, (picture) => turned(cropped(flipped(picture, "vertical"), "top", 10), 90));

    const style = (editor.view.dom.querySelector("img") as HTMLElement).style;
    expect(style.transform).toBe("rotate(90deg) scale(1, -1)");
    expect(style.clipPath).toBe("inset(10% 0% 0% 0%)");
    const { elements: saved } = reconcileWithIds((editor.getJSON().content ?? []) as Record<string, unknown>[], [element]);
    expect(saved[0].image).toEqual({ ...WORD_PICTURE, crop: { left: 0, top: 0.1, right: 0, bottom: 0 }, rotation: 90, flipVertical: true });
    expect(pictureAt(editor, element.id)?.rotation).toBe(90);
    expect(pictureAt(editor, "no-such-picture")).toBeUndefined();
  });

  it("knows a picture clicked on is the one selected", () => {
    const { editor, element } = open(WORD_PICTURE);
    editor.commands.setNodeSelection(0);

    expect(getSelectedElementId(editor)).toBe(element.id);
  });
});
