import type { Editor } from "@tiptap/react";

import { CM_TO_PX } from "./tableLook";
import { NO_PICTURE, type PictureAttr } from "./pictureLook";

/**
 * Cropping, turning and flipping a picture in the editor (tracker DOCX-018B). Each change
 * rides on the image node's picture attribute -- what pictureLook.ts draws and
 * tiptapToDocument.ts saves -- so the Word and PDF exports follow it. A crop leaves at
 * least a tenth of the picture across and down (the model refuses none left).
 */

export type CropSide = "left" | "top" | "right" | "bottom";

const OPPOSITE: Record<CropSide, CropSide> = { left: "right", right: "left", top: "bottom", bottom: "top" };
// The most a crop may take off one way, both sides together.
const MAX_CROP = 0.9;

const round = (value: number, places = 4) => Math.round(value * 10 ** places) / 10 ** places;

/** Turned by `degrees` more (clockwise, as Word turns): 0 is no turn at all. */
export function turned(picture: PictureAttr | null, degrees: number): PictureAttr {
  const base = picture ?? NO_PICTURE;
  return withRotation(base, (base.rotation ?? 0) + degrees);
}

/** Turned to `degrees` (any, kept to 0-359.99). */
export function withRotation(picture: PictureAttr | null, degrees: number): PictureAttr {
  const base = picture ?? NO_PICTURE;
  const rotation = round((((degrees % 360) + 360) % 360), 2);
  return { ...base, rotation: rotation === 0 || rotation === 360 ? null : rotation };
}

/** Flipped across, or up and down. */
export function flipped(picture: PictureAttr | null, axis: "horizontal" | "vertical"): PictureAttr {
  const base = picture ?? NO_PICTURE;
  return axis === "horizontal" ? { ...base, flipHorizontal: !base.flipHorizontal } : { ...base, flipVertical: !base.flipVertical };
}

/** One side cropped to `percent` of the picture -- at most what leaves a tenth with the side opposite. */
export function cropped(picture: PictureAttr | null, side: CropSide, percent: number): PictureAttr {
  const base = picture ?? NO_PICTURE;
  const crop = { ...(base.crop ?? { left: 0, top: 0, right: 0, bottom: 0 }) };
  const share = Number.isFinite(percent) ? Math.max(0, percent / 100) : 0;
  crop[side] = round(Math.min(share, MAX_CROP - crop[OPPOSITE[side]]));
  const none = crop.left === 0 && crop.top === 0 && crop.right === 0 && crop.bottom === 0;
  return { ...base, crop: none ? null : crop };
}

/** As it came: no crop, turn or flip (its size and placement kept). */
export function uncropped(picture: PictureAttr | null): PictureAttr {
  return { ...(picture ?? NO_PICTURE), crop: null, rotation: null, flipHorizontal: false, flipVertical: false };
}

/** The image node with `elementId`, and where it is. */
function findImage(editor: Editor, elementId: string) {
  let found: { pos: number; attrs: Record<string, unknown> } | null = null;
  editor.state.doc.descendants((node, pos) => {
    if (found) return false;
    if (node.type.name === "image" && node.attrs.elementId === elementId) {
      found = { pos, attrs: node.attrs };
      return false;
    }
    return true;
  });
  return found as { pos: number; attrs: Record<string, unknown> } | null;
}

/** The picture attribute of the image node with `elementId`, or null when there's no such image. */
export function pictureAt(editor: Editor, elementId: string): PictureAttr | null | undefined {
  const image = findImage(editor, elementId);
  return image ? ((image.attrs.picture ?? null) as PictureAttr | null) : undefined;
}

/**
 * Changes the picture of the image node with `elementId`. A picture with no size of its own (one
 * pasted here) gets the size it is shown at first, so a crop or a turn can be drawn and kept.
 */
export function updatePicture(editor: Editor, elementId: string, change: (picture: PictureAttr | null) => PictureAttr): boolean {
  const image = findImage(editor, elementId);
  if (!image) return false;
  let picture = change((image.attrs.picture ?? null) as PictureAttr | null);
  if (!picture.widthCm || !picture.heightCm) {
    const dom = editor.view.nodeDOM(image.pos);
    const img = dom instanceof HTMLImageElement ? dom : dom instanceof HTMLElement ? dom.querySelector("img") : null;
    if (img && img.offsetWidth && img.offsetHeight) {
      picture = { ...picture, widthCm: round(img.offsetWidth / CM_TO_PX, 2), heightCm: round(img.offsetHeight / CM_TO_PX, 2) };
    }
  }
  const { pos, attrs } = image;
  return editor
    .chain()
    .command(({ tr }) => {
      tr.setNodeMarkup(pos, undefined, { ...attrs, picture });
      return true;
    })
    .run();
}
