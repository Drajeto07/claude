import { describe, expect, it } from "vitest";

import { basePage, columnShift, sectionPage, shiftedMargin } from "./sectionPages";

/**
 * Each section's page in the editor (tracker DOCX-015): its own size or the
 * document's turned to its orientation, its own margins and header and footer
 * distances over the document's -- as the PDF has them -- and the text column its
 * blocks are moved to.
 */

const PX_PER_CM = 96 / 2.54;
const A4 = { pageWidthMm: 210, pageHeightMm: 297, marginTopCm: 2.5, marginBottomCm: 2.5, marginLeftCm: 2, marginRightCm: 2 };

describe("section pages", () => {
  const base = basePage(A4, { headerDistanceCm: 1 });

  it("measures the document's own page in CSS pixels, with Word's header distance unless it has one", () => {
    expect(base.width).toBeCloseTo(210 * (96 / 25.4));
    expect(base.marginLeft).toBeCloseTo(2 * PX_PER_CM);
    expect(base.headerDistance).toBeCloseTo(1 * PX_PER_CM);
    expect(basePage(A4).footerDistance).toBeCloseTo(1.27 * PX_PER_CM);
  });

  it("draws the last section on its own paper when the app lists none like it (DOCX-015A)", () => {
    const custom = basePage(A4, { pageWidthMm: 200, pageHeightMm: 250 });
    expect([custom.width, custom.height]).toEqual([200 * (96 / 25.4), 250 * (96 / 25.4)]);
    expect(custom.marginLeft).toBeCloseTo(2 * PX_PER_CM); // the margins are still the document's
    expect(basePage(A4, { pageWidthMm: 200 }).width).toBeCloseTo(210 * (96 / 25.4)); // half a size is none
  });

  it("gives a section its own size, or the document's turned to its orientation", () => {
    const turned = sectionPage({ orientation: "landscape" }, base);
    expect([turned.width, turned.height]).toEqual([base.height, base.width]);
    expect(sectionPage({ orientation: "portrait" }, base)).toEqual(base); // the document's already is
    const letter = sectionPage({ pageWidthMm: 215.9, pageHeightMm: 279.4, orientation: "portrait" }, base);
    expect(letter.width).toBeCloseTo(215.9 * (96 / 25.4));
    expect(sectionPage(null, base)).toEqual(base);
  });

  it("gives a section its own margins and distances over the document's", () => {
    const own = sectionPage({ marginLeftCm: 3, headerDistanceCm: 2 }, base);
    expect(own.marginLeft).toBeCloseTo(3 * PX_PER_CM);
    expect(own.marginRight).toBe(base.marginRight);
    expect(own.headerDistance).toBeCloseTo(2 * PX_PER_CM);
    expect(own.footerDistance).toBe(base.footerDistance);
  });

  it("moves a wider section's text column out on both sides, a wider margin's in", () => {
    const turned = sectionPage({ orientation: "landscape" }, base);
    const { left, right } = columnShift(turned, base);
    expect(left).toBeCloseTo(-(base.height - base.width) / 2);
    expect(right).toBeCloseTo(left);
    expect(columnShift(base, base)).toEqual({ left: 0, right: 0 });
    expect(columnShift(sectionPage({ marginLeftCm: 3 }, base), base).left).toBeCloseTo(PX_PER_CM);
  });

  it("moves a block's margin over its own, and leaves an automatic one", () => {
    expect(shiftedMargin("text-align:center;margin-left:1.27cm", "left", -120.04)).toBe("calc(1.27cm + -120px)");
    expect(shiftedMargin(null, "right", 12.34)).toBe("calc(0px + 12.3px)");
    expect(shiftedMargin("display:block;margin-left:auto;margin-right:auto", "left", -50)).toBe("auto");
    expect(shiftedMargin("padding-left:2px", "left", 5)).toBe("calc(0px + 5px)"); // not a margin
  });
});
