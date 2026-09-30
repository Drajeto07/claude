import { Extension } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

import type { ImageContent } from "@/types/document";

/**
 * A Word picture's own look in the editor (tracker DOCX-018): its type, name, size,
 * crop, turn, flips and placement ride on the image node -- not rendered;
 * tiptapToDocument.ts gives them back on save -- and a plugin draws the size, crop and
 * turn. A crop is shown by sizing the picture as if whole, clipping it to the kept
 * part and pulling its edges in, so the kept part takes the place the picture has in
 * Word. A floating picture is shown in line (the import report says so).
 */

export type PictureAttr = Pick<ImageContent, "mime" | "name" | "widthCm" | "heightCm" | "crop" | "rotation" | "flipHorizontal" | "flipVertical" | "placement">;

export const NO_PICTURE: PictureAttr = {
  mime: null,
  name: null,
  widthCm: null,
  heightCm: null,
  crop: null,
  rotation: null,
  flipHorizontal: false,
  flipVertical: false,
  placement: null,
};

export const PictureAttribute = Extension.create({
  name: "pictureAttribute",
  addGlobalAttributes() {
    return [{ types: ["image"], attributes: { picture: { default: null, rendered: false } } }];
  },
});

/** A picture's own look as the editor keeps it: null for one with none (pasted or made here). */
export function pictureOf(image: ImageContent): PictureAttr | null {
  const picture: PictureAttr = {
    mime: image.mime,
    name: image.name,
    widthCm: image.widthCm,
    heightCm: image.heightCm,
    crop: image.crop,
    rotation: image.rotation,
    flipHorizontal: image.flipHorizontal,
    flipVertical: image.flipVertical,
    placement: image.placement,
  };
  const none = Object.entries(picture).every(([key, value]) => (key.startsWith("flip") ? value === false : value === null));
  return none ? null : picture;
}

const LENGTH = /^\s*(-?\d+(?:\.\d+)?)(%|px|cm|mm|pt|in|em)\s*$/;

/** The width a picture is drawn at: its style's (a width rule, or a pasted size), else its own from Word. */
function widthOf(node: ProseMirrorNode, picture: PictureAttr): { value: number; unit: string } | null {
  const style = String(node.attrs.style ?? "");
  const fromStyle = /(?:^|;)\s*width\s*:\s*([^;]+)/i.exec(style)?.[1];
  const match = fromStyle ? LENGTH.exec(fromStyle) : null;
  if (match) return { value: Number(match[1]), unit: match[2] };
  const pasted = Number(node.attrs.width);
  if (Number.isFinite(pasted) && pasted > 0) return { value: pasted, unit: "px" };
  return picture.widthCm ? { value: picture.widthCm, unit: "cm" } : null;
}

function round(value: number): number {
  return Math.round(value * 10_000) / 10_000;
}

/** A picture's style: its size and proportions, crop and turn (see the module note). */
export function pictureStyle(node: ProseMirrorNode, picture: PictureAttr): string | null {
  const width = widthOf(node, picture);
  const aspect = picture.widthCm && picture.heightCm ? picture.widthCm / picture.heightCm : null; // as Word draws it
  const style: string[] = [];
  const crop = picture.crop;
  const turned = picture.rotation || picture.flipHorizontal || picture.flipVertical;
  const askew = Boolean(picture.rotation && picture.rotation % 180); // off its sides: it takes another room
  if ((crop || askew) && width && aspect) {
    const { left, top, right, bottom } = crop ?? { left: 0, top: 0, right: 0, bottom: 0 };
    const across = 1 - left - right;
    const down = 1 - top - bottom;
    const unit = width.unit;
    // The part kept, as Word draws it (a height in % goes by the width, as vertical margins do) ...
    const shown = width.value;
    const high = shown / aspect;
    // ... drawn as part of the whole picture, and the room its turned outline takes, as Word lays it out.
    const whole = shown / across;
    const wholeHigh = high / down;
    const angle = ((picture.rotation ?? 0) * Math.PI) / 180;
    const wide = Math.abs(shown * Math.cos(angle)) + Math.abs(high * Math.sin(angle));
    const tall = Math.abs(shown * Math.sin(angle)) + Math.abs(high * Math.cos(angle));
    const aside = (wide - shown) / 2;
    const above = (tall - high) / 2;
    const own = String(node.attrs.style ?? ""); // its alignment: margins set to auto (a rule)
    const centred = /margin-left\s*:\s*auto/i.test(own) && /margin-right\s*:\s*auto/i.test(own);
    const toRight = /margin-left\s*:\s*auto/i.test(own) && !centred;
    const shift = `${round(aside - left * whole)}${unit}`;
    const room = `${round(wide)}${unit}`;
    const lead = centred ? `calc((100% - ${room}) / 2 + ${shift})` : toRight ? `calc(100% - ${room} + ${shift})` : shift;
    style.push(
      `display:block`,
      `max-width:none`,
      `width:${round(whole)}${unit}`,
      `aspect-ratio:${round(whole / wholeHigh)}`,
      ...(crop ? [`clip-path:inset(${round(top * 100)}% ${round(right * 100)}% ${round(bottom * 100)}% ${round(left * 100)}%)`] : []),
      // top, right, bottom, left: the order the margin shorthand takes them in
      `margin-top:${round(above - top * wholeHigh)}${unit}`,
      `margin-right:${round(aside - right * whole)}${unit}`,
      `margin-bottom:${round(above - bottom * wholeHigh)}${unit}`,
      `margin-left:${lead}`,
    );
    if (turned) style.push(`transform-origin:${round((left + across / 2) * 100)}% ${round((top + down / 2) * 100)}%`);
  } else {
    if (width && width.unit === "cm") style.push(`width:${width.value}cm`, "max-width:100%");
    if (aspect) style.push(`aspect-ratio:${round(aspect)}`, "height:auto");
  }
  if (turned) {
    const transform = [
      picture.rotation ? `rotate(${picture.rotation}deg)` : null,
      picture.flipHorizontal || picture.flipVertical ? `scale(${picture.flipHorizontal ? -1 : 1}, ${picture.flipVertical ? -1 : 1})` : null,
    ].filter(Boolean);
    style.push(`transform:${transform.join(" ")}`);
  }
  return style.length ? style.join(";") : null;
}

function pictureDecorations(doc: ProseMirrorNode): Decoration[] {
  const into: Decoration[] = [];
  doc.descendants((node, pos) => {
    if (node.type.name !== "image") return true;
    const picture = (node.attrs.picture ?? null) as PictureAttr | null;
    const style = picture ? pictureStyle(node, picture) : null;
    if (style) into.push(Decoration.node(pos, pos + node.nodeSize, { style }));
    return false;
  });
  return into;
}

const pictureLookKey = new PluginKey<DecorationSet>("pictureLook");

export const PictureLook = Extension.create({
  name: "pictureLook",
  addProseMirrorPlugins() {
    return [
      new Plugin<DecorationSet>({
        key: pictureLookKey,
        state: {
          init: (_, state) => DecorationSet.create(state.doc, pictureDecorations(state.doc)),
          apply: (tr, set) => (tr.docChanged ? DecorationSet.create(tr.doc, pictureDecorations(tr.doc)) : set),
        },
        props: {
          decorations: (state) => pictureLookKey.getState(state),
        },
      }),
    ];
  },
});
