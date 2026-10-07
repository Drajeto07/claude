import { describe, expect, it } from "vitest";

import { cssFontStack, fallbackStack, fontKind } from "./fontStack";

/** The editor's CSS font stacks are the PDF export's fallbacks (tracker FONT-005). */

describe("a font's CSS stack", () => {
  it("lists the fonts made with its widths, then its kind's, then the generic family", () => {
    expect(cssFontStack("Calibri")).toMatch(/^"Calibri", "Carlito", "Arial", "Liberation Sans", .*, sans-serif$/);
    expect(cssFontStack("Times New Roman")).toMatch(/^"Times New Roman", "Liberation Serif", "Tinos", .*, serif$/);
    expect(cssFontStack("Consolas")).toMatch(/^"Consolas", "Courier New", .*, monospace$/);
  });

  it("names each font once, matched in any case, and leaves a list as it is", () => {
    const stack = fallbackStack("arial");
    expect(stack[0]).toBe("arial");
    expect(new Set(stack.map((name) => name.toLowerCase())).size).toBe(stack.length);
    expect(cssFontStack('"Aptos", sans-serif')).toBe('"Aptos", sans-serif');
    expect(cssFontStack("")).toBe("");
  });

  it("tells the kind of a font by its name, as the export does", () => {
    expect([fontKind("Constantia"), fontKind("Segoe UI"), fontKind("Courier"), fontKind("PT Sans Serif")]).toEqual(["serif", "sans", "mono", "sans"]);
  });
});
