import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Document, Element } from "@/types/document";

import { documentToTiptapJSON } from "./documentToTiptap";
import { editorExtensions } from "./extensions";
import { breakAfter } from "./pagination";
import { sectionBreakLabel, sectionSummary, type SectionSettings } from "./sectionBreak";
import { reconcileWithIds } from "./tiptapToDocument";

/**
 * A Word section break in the editor (tracker DOCX-015): its settings go through the
 * editor unchanged, it says how the next section starts and what the pages above it
 * are set to, and pagination starts a new page after it unless the next section is
 * continuous -- an even or odd one where it says so.
 */

const editors: Editor[] = [];

afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

const SETTINGS: SectionSettings = {
  start: "oddPage",
  orientation: "landscape",
  pageWidthMm: 279.4,
  pageHeightMm: 215.9,
  marginTopCm: 2.54,
  marginBottomCm: 2.54,
  marginLeftCm: 3.17,
  marginRightCm: 3.17,
  headerDistanceCm: 1.27,
  footerDistanceCm: 1.27,
  columns: 2,
  columnSpacingCm: 1.25,
  pageNumberStart: 1,
  pageNumberFormat: "lowerRoman",
};

function element(overrides: Partial<Element>): Element {
  return {
    id: crypto.randomUUID(),
    type: "paragraph",
    content: "",
    inline: null,
    listItems: null,
    ordered: false,
    table: null,
    image: null,
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
    ...overrides,
  } as Element;
}

describe("section breaks in the editor", () => {
  it("keeps a section break's settings through the editor", () => {
    const elements = [
      element({ content: "Wide.", inline: [{ text: "Wide.", marks: [] }], order: 0 }),
      element({ type: "section_break", sectionBreak: SETTINGS, order: 1 }),
      element({ content: "Narrow.", inline: [{ text: "Narrow.", marks: [] }], order: 2 }),
    ];
    const document = { elements, resolvedStyles: {}, settings: {} } as unknown as Document;
    const editor = new Editor({ extensions: editorExtensions, content: documentToTiptapJSON(document) });
    editors.push(editor);

    const { elements: saved } = reconcileWithIds((editor.getJSON().content ?? []) as Record<string, unknown>[], elements);

    expect(saved.map((item) => item.type)).toEqual(["paragraph", "section_break", "paragraph"]);
    expect(saved[1].sectionBreak).toEqual(SETTINGS);
    expect(saved[1].id).toBe(elements[1].id);
    expect(editor.getHTML()).toContain("Section break (odd page)");
    expect(editor.getHTML()).toContain("Above: landscape · 27.9 × 21.6 cm · 2 columns · pages from 1");
  });

  it("names how the next section starts", () => {
    expect(sectionBreakLabel({ ...SETTINGS, start: "continuous" })).toBe("Section break (continuous)");
    expect(sectionBreakLabel(null)).toBe("Section break (next page)");
    expect(sectionSummary({ start: "nextPage" } as SectionSettings)).toBe("");
  });

  it("starts a new page after it unless the next section is continuous", () => {
    const editor = new Editor({ extensions: editorExtensions, content: "<p>x</p>" });
    editors.push(editor);
    const node = (start: string) => editor.schema.nodes.sectionBreak.create({ section: { ...SETTINGS, start } });

    expect(breakAfter(node("nextPage"))).toBe("any");
    expect(breakAfter(node("continuous"))).toBe(false);
    expect(breakAfter(node("evenPage"))).toBe("even");
    expect(breakAfter(node("oddPage"))).toBe("odd");
    expect(breakAfter(editor.schema.nodes.pageBreak.create())).toBe("any");
    expect(breakAfter(editor.schema.nodes.paragraph.create())).toBe(false);
  });
});
