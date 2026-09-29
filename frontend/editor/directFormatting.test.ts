import { readFileSync } from "node:fs";
import path from "node:path";

import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Document, Element } from "@/types/document";

import { documentToTiptapJSON } from "./documentToTiptap";
import { editorExtensions } from "./extensions";
import { MARK_ORDER, NOT_KEPT, reconcileWithIds, sameContent, widthPercent, type Layout } from "./tiptapToDocument";

/**
 * Formatting the editor holds on blocks themselves (tracker EDIT-008, EDIT-009,
 * EDIT-011, EDIT-012): alignment typed with a shortcut or pasted, and a picture's
 * size, are saved as the element's own style; what the document can't keep is
 * named instead of dropped without a word.
 */

type Json = { type?: string; text?: string; attrs?: Record<string, unknown>; content?: Json[]; marks?: { type: string; attrs?: Record<string, unknown> }[] };

const PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
// A4 with 2 cm margins: 170 mm of text width, 642.5 px.
const LAYOUT: Layout = {
  resolvedStyles: { Paragraph: { "text-align": "left" }, "Heading 1": { "text-align": "left" }, Image: {} },
  settings: { pageWidthMm: 210, marginLeftCm: 2, marginRightCm: 2 } as Layout["settings"],
};
const editors: Editor[] = [];

afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

function editorWith(content: string | Record<string, unknown>): Editor {
  const editor = new Editor({ extensions: editorExtensions, content });
  editors.push(editor);
  return editor;
}

function reconcile(editor: Editor, previous: Element[] = [], layout: Layout = LAYOUT) {
  return reconcileWithIds((editor.getJSON().content ?? []) as Json[] as Record<string, unknown>[], previous, layout);
}

describe("alignment on a paragraph or heading", () => {
  it("pasted or typed with a shortcut is saved as the block's own alignment", () => {
    const editor = editorWith('<p style="text-align: center">Centred</p><h1>Plain</h1><p>Left</p>');
    editor.commands.setTextSelection(editor.state.doc.child(0).nodeSize + 2); // in the heading
    editor.commands.setTextAlign("right");

    const { styles, nodeIds, notes } = reconcile(editor);

    expect(styles).toEqual([
      { elementId: nodeIds[0], property: "alignment", value: "center", unit: null },
      { elementId: nodeIds[1], property: "alignment", value: "right", unit: null },
    ]);
    expect(notes).toEqual([]);
  });

  it("isn't sent again once the element has it, or when its kind already gives it", () => {
    const own: Element = { id: "p1", type: "paragraph", content: "x", inline: [{ text: "x", marks: [] }], styleRef: "p1", order: 0 } as unknown as Element;
    const layout: Layout = { ...LAYOUT, resolvedStyles: { ...LAYOUT.resolvedStyles, p1: { "text-align": "center" } } };
    const document = { elements: [own], ...layout } as unknown as Document;
    const editor = editorWith(documentToTiptapJSON(document));

    expect(editor.getJSON().content?.[0].attrs?.textAlign).toBe("center"); // its own alignment, carried by the block
    expect(reconcile(editor, [own], layout).styles).toEqual([]);
    expect(reconcile(editorWith('<p style="text-align: left">x</p>')).styles).toEqual([]);
  });

  it("goes with the new block when a paragraph is split, as in Word", () => {
    const own: Element = { id: "p1", type: "paragraph", content: "One", inline: [{ text: "One", marks: [] }], styleRef: "p1", order: 0 } as unknown as Element;
    const layout: Layout = { ...LAYOUT, resolvedStyles: { ...LAYOUT.resolvedStyles, p1: { "text-align": "center" } } };
    const editor = editorWith(documentToTiptapJSON({ elements: [own], ...layout } as unknown as Document));
    editor.commands.setTextSelection(editor.state.doc.child(0).nodeSize - 1);
    editor.commands.splitBlock();
    editor.commands.insertContent("Two");

    const { styles, nodeIds } = reconcile(editor, [own], layout);

    expect(nodeIds[0]).toBe("p1");
    expect(styles).toEqual([{ elementId: nodeIds[1], property: "alignment", value: "center", unit: null }]);
  });

  it("survives pasting into an empty paragraph, which the pasted paragraphs replace", () => {
    // jsdom has no ClipboardEvent; the editor's pasteHTML only needs one to exist.
    (globalThis as Record<string, unknown>).ClipboardEvent ??= class extends Event {
      clipboardData = null;
    };
    const editor = editorWith("<p>First</p><p></p>");
    editor.commands.setTextSelection(editor.state.doc.content.size - 1);
    editor.view.pasteHTML('<p style="text-align: center">A centred line</p><p>After</p>');

    const nodes = (editor.getJSON().content ?? []) as Json[];
    expect(nodes.map((node) => [node.attrs?.textAlign ?? null, node.content?.[0]?.text])).toEqual([
      [null, "First"],
      ["center", "A centred line"],
      [null, "After"],
    ]);

    const typedInto = editorWith("<p>First</p>");
    typedInto.commands.setTextSelection(typedInto.state.doc.content.size - 1);
    typedInto.view.pasteHTML('<p style="text-align: center">joins</p>');
    expect(typedInto.getJSON().content?.[0]).toMatchObject({ attrs: { textAlign: null }, content: [{ text: "Firstjoins" }] }); // into text: as any editor does
  });

  it("inside a list, a quote or a table cell's other paragraphs is named, not dropped silently", () => {
    const editor = editorWith('<blockquote><p style="text-align: right">Quoted</p></blockquote><ul><li><p style="text-align: center">Item</p></li></ul>');

    const { styles, notes } = reconcile(editor);

    expect(styles).toEqual([]);
    expect(notes).toEqual([NOT_KEPT.nestedAlignment]);
  });
});

describe("a picture's size", () => {
  it("becomes its width as a share of the text width", () => {
    expect(widthPercent("321", LAYOUT.settings)).toBe(50);
    expect(widthPercent("321px", LAYOUT.settings)).toBe(50);
    expect(widthPercent("40%", LAYOUT.settings)).toBe(40);
    expect(widthPercent("5000", LAYOUT.settings)).toBe(100); // never wider than the text
    expect(widthPercent("auto", LAYOUT.settings)).toBeNull();

    const editor = editorWith(`<img src="${PNG}" width="321" height="120">`);
    const { styles, nodeIds } = reconcile(editor);
    expect(styles).toEqual([{ elementId: nodeIds[0], property: "imageWidth", value: "50", unit: "%" }]);
  });

  it("isn't sent again once the element has that width, and one the document can't hold is named", () => {
    const picture: Element = { id: "i1", type: "image", content: "", image: { src: PNG, assetId: null, alt: null, title: null }, styleRef: "i1", order: 0 } as unknown as Element;
    const layout: Layout = { ...LAYOUT, resolvedStyles: { ...LAYOUT.resolvedStyles, i1: { width: "50%" } } };
    const editor = editorWith({ type: "doc", content: [{ type: "image", attrs: { src: PNG, width: "321", elementId: "i1" } }] });
    expect(reconcile(editor, [picture], layout).styles).toEqual([]);

    const odd = editorWith({ type: "doc", content: [{ type: "image", attrs: { src: PNG, width: "auto" } }] });
    expect(reconcile(odd).notes).toEqual([NOT_KEPT.pictureSize]);
  });
});

describe("tables", () => {
  it("keep a cell's own alignment as its column's, a cell's own where its column's differ, and pasted widths", () => {
    const aligned = editorWith('<table><tr><td align="center"><p>a</p></td><td><p>b</p></td></tr><tr><td style="text-align: center"><p>c</p></td><td><p>d</p></td></tr></table>');
    const { elements, notes } = reconcile(aligned);
    expect(elements[0].table?.alignments).toEqual(["center", null]);
    expect(notes).toEqual([]);

    const mixed = editorWith(
      // A table pasted from Word or Google Docs carries its column widths in a <colgroup>.
      '<table><colgroup><col width="150"><col width="80"></colgroup><tr><td><p style="text-align: right">a</p></td><td><p>b</p></td></tr><tr><td><p>c</p></td><td><p>d</p></td></tr></table>',
    );
    const { elements: kept, notes: none } = reconcile(mixed);
    expect(none).toEqual([]); // kept since DOCX-017
    expect(kept[0].table?.rows[0].cells[0].align).toBe("right");
    expect(kept[0].table?.columnWidthsCm).toEqual([3.97, 2.12]); // 150 and 80 px
  });
});

describe("character formatting the document can't store", () => {
  it("is named once, and a transparent background isn't a loss", () => {
    const editor = editorWith(
      '<p><span style="color: hsl(0, 100%, 50%)">red</span> <span style="font-size: 1.2em">big</span> <span style="background-color: transparent">plain</span> <span style="color: hsl(120, 100%, 25%)">green</span></p>',
    );

    const { notes, elements } = reconcile(editor);

    expect(notes.sort()).toEqual([NOT_KEPT.color, NOT_KEPT.size].sort());
    expect(elements[0].content).toBe("red big plain green"); // the words are all there
  });
});

describe("a link's title", () => {
  it("is saved with the link and shown again as its tooltip", () => {
    const editor = editorWith('<p><a href="https://example.com/guide" title="The  full guide">the guide</a></p>');

    const { elements, notes } = reconcile(editor);
    const link = elements[0].inline?.[0].marks.find((mark) => mark.type === "link");
    expect(link).toMatchObject({ href: "https://example.com/guide", title: "The full guide" });
    expect(notes).toEqual([]);

    const reopened = editorWith(documentToTiptapJSON({ elements, ...LAYOUT } as unknown as Document));
    const marks = (reopened.getJSON().content?.[0].content?.[0].marks ?? []) as { type: string; attrs?: Record<string, unknown> }[];
    expect(marks.find((mark) => mark.type === "link")?.attrs?.title).toBe("The full guide");
  });

  it("is shortened to what the document holds, and says so", () => {
    const editor = editorWith(`<p><a href="https://example.com" title="${"t".repeat(600)}">long</a></p>`);

    const { elements, notes } = reconcile(editor);

    expect(elements[0].inline?.[0].marks[0].title).toHaveLength(500);
    expect(notes).toEqual([NOT_KEPT.linkTitle]);
  });
});

describe("the order of a run's marks", () => {
  it("is the backend's, so opening a document saves nothing", () => {
    const unset = { href: null, title: null, fontFamily: null, fontSizePt: null, color: null, backgroundColor: null };
    const element = {
      id: "p1",
      type: "paragraph",
      content: "a bold link",
      order: 0,
      ordered: false,
      styleRef: "Paragraph",
      inline: [
        {
          text: "a bold link",
          marks: [
            { ...unset, type: "bold" },
            { ...unset, type: "italic" },
            { ...unset, type: "link", href: "https://example.com" },
            { ...unset, type: "textStyle", color: "#FF0000" },
          ],
        },
      ],
    } as unknown as Element;
    const editor = editorWith(documentToTiptapJSON({ elements: [element], ...LAYOUT } as unknown as Document));

    const { elements } = reconcile(editor, [element]);

    expect(elements[0].inline?.[0].marks.map((mark) => mark.type)).toEqual(["bold", "italic", "link", "textStyle"]);
    expect(sameContent(elements, [element])).toBe(true);
  });

  it("follows the backend's MarkType", () => {
    const schema = JSON.parse(readFileSync(path.join(process.cwd(), "types", "generated", "openapi.json"), "utf8"));
    expect(MARK_ORDER).toEqual(schema.components.schemas.MarkType.enum);
  });
});
