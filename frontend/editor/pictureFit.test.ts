import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { describe, expect, it } from "vitest";

import { PICTURE_PAGE_FIT, pictureFit } from "@/editor/pagination";
import { basePage, sectionPage } from "@/editor/sectionPages";

/** B-037: how a top-level picture is kept inside its page -- a max-width from the page's text height and the
 * picture's own proportions, per section (size, orientation, margins), never from a measurement. */

const A4 = basePage({ pageWidthMm: 210, pageHeightMm: 297, marginTopCm: 2.5, marginBottomCm: 2.5, marginLeftCm: 2.5, marginRightCm: 2.5 });

function image(picture: Record<string, unknown> | null = null): ProseMirrorNode {
  return { type: { name: "image" }, attrs: { picture } } as unknown as ProseMirrorNode;
}

function loaded(width: number, height: number): HTMLImageElement {
  const element = document.createElement("img");
  Object.defineProperty(element, "naturalWidth", { value: width });
  Object.defineProperty(element, "naturalHeight", { value: height });
  return element;
}

function maxWidth(style: string | null): number | null {
  const found = style && /min\(100%, (\d+)px\)/.exec(style);
  return found ? Number(found[1]) : null;
}

const textHeight = (box = A4) => box.height - box.marginTop - box.marginBottom;

describe("pictureFit", () => {
  it("bounds a phone screenshot so that, in its own proportions, it takes at most the page's share of the text height", () => {
    const style = pictureFit(image(), loaded(946, 2048), A4);
    expect(style).toMatch(/^max-width:min\(100%, \d+px\) !important$/);
    const width = maxWidth(style)!;
    expect(width).toBe(Math.floor(PICTURE_PAGE_FIT * textHeight() * (946 / 2048)));
    expect(width / (946 / 2048)).toBeLessThanOrEqual(PICTURE_PAGE_FIT * textHeight()); // its height at that width fits
  });

  it("gives a wide picture a bound wider than the column, so the column (100%) is what holds it -- it isn't made smaller", () => {
    const columnWidth = A4.width - A4.marginLeft - A4.marginRight;
    expect(maxWidth(pictureFit(image(), loaded(3000, 1000), A4))!).toBeGreaterThan(columnWidth);
  });

  it("takes a Word picture's own proportions (as pictureLook draws it) over its file's", () => {
    const style = pictureFit(image({ widthCm: 10, heightCm: 20 }), loaded(100, 100), A4);
    expect(maxWidth(style)).toBe(Math.floor(PICTURE_PAGE_FIT * textHeight() * 0.5));
  });

  it("goes by the page of the picture's own section: a landscape section's page is lower, so its bound is smaller", () => {
    const landscape = sectionPage({ orientation: "landscape" }, A4);
    const portraitBound = maxWidth(pictureFit(image(), loaded(946, 2048), A4))!;
    const landscapeBound = maxWidth(pictureFit(image(), loaded(946, 2048), landscape))!;
    expect(landscapeBound).toBe(Math.floor(PICTURE_PAGE_FIT * textHeight(landscape) * (946 / 2048)));
    expect(landscapeBound).toBeLessThan(portraitBound);
    const wideMargins = sectionPage({ marginTopCm: 5, marginBottomCm: 5 }, A4);
    expect(maxWidth(pictureFit(image(), loaded(946, 2048), wideMargins))!).toBeLessThan(portraitBound);
  });

  it("leaves alone what it can't size or mustn't: not loaded yet, cropped, turned askew, not a picture", () => {
    expect(pictureFit(image(), loaded(0, 0), A4)).toBeNull();
    expect(pictureFit(image({ widthCm: 5, heightCm: 10, crop: { left: 0.1, top: 0, right: 0, bottom: 0 } }), loaded(10, 20), A4)).toBeNull();
    expect(pictureFit(image({ widthCm: 5, heightCm: 10, rotation: 90 }), loaded(10, 20), A4)).toBeNull();
    expect(pictureFit(image({ widthCm: 5, heightCm: 10, rotation: 180 }), loaded(10, 20), A4)).not.toBeNull(); // upside down: same room
    expect(pictureFit({ type: { name: "paragraph" }, attrs: {} } as unknown as ProseMirrorNode, loaded(10, 20), A4)).toBeNull();
    expect(pictureFit(image(), document.createElement("div"), A4)).toBeNull();
  });

  it("is the same every time for the same page and picture (no measurement in it, so layouts can't swing)", () => {
    const element = loaded(946, 2048);
    expect(pictureFit(image(), element, A4)).toBe(pictureFit(image(), element, A4));
  });
});
