import { getSchema } from "@tiptap/core";
import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Document, Element } from "@/types/document";

import { documentToTiptapJSON } from "./documentToTiptap";
import { editorExtensions } from "./extensions";
import { reconcileWithIds, sameContent, UnsupportedContentError } from "./tiptapToDocument";

/**
 * Content nested inside table cells, list items and quotes (tracker EDIT-001..006):
 * what the editor shows is what gets saved, and a saved document opens again as the
 * same editor content. Nothing is left out on the way; what can't be stored stops
 * the save with an error instead.
 */

type Json = { type?: string; text?: string; attrs?: Record<string, unknown>; content?: Json[]; marks?: { type: string; attrs?: Record<string, unknown> }[] };

const PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
const editors: Editor[] = [];

function editorWith(content: string | Record<string, unknown>): Editor {
  const editor = new Editor({ extensions: editorExtensions, content });
  editors.push(editor);
  return editor;
}

afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

function topLevel(editor: Editor): Json[] {
  return (editor.getJSON().content ?? []) as Json[];
}

function save(editor: Editor, previous: Element[] = []): Element[] {
  return reconcileWithIds(topLevel(editor) as Record<string, unknown>[], previous).elements;
}

function asDocument(elements: Element[]): Document {
  return { id: "d", elements, resolvedStyles: {} } as unknown as Document;
}

// The attributes that are content or structure; ids, styles and link defaults are the editor's own.
const KEPT_ATTRS = ["level", "language", "start", "type", "checked", "colspan", "rowspan", "backgroundColor", "src", "alt", "title", "textAlign"];

function structure(node: Json): unknown {
  const attrs = Object.fromEntries(
    Object.entries(node.attrs ?? {}).filter(([key, value]) => KEPT_ATTRS.includes(key) && value !== null && value !== undefined && !(key === "start" && value === 1)),
  );
  const marks = (node.marks ?? []).map((mark) => (mark.type === "link" ? `link:${mark.attrs?.href}` : mark.type)).sort();
  return {
    type: node.type,
    ...(node.text !== undefined ? { text: node.text } : {}),
    ...(Object.keys(attrs).length ? { attrs } : {}),
    ...(marks.length ? { marks } : {}),
    ...(node.content ? { content: node.content.map(structure) } : {}),
  };
}

function withoutTrailingBlank(nodes: Json[]): Json[] {
  const copy = [...nodes];
  while (copy.length && copy[copy.length - 1].type === "paragraph" && !copy[copy.length - 1].content?.length) copy.pop();
  return copy;
}

function allText(nodes: Json[]): string {
  return nodes.map((node) => (node.text ?? "") + allText(node.content ?? [])).join("");
}

/** Saves `html` as pasted, opens the saved document again, and saves that: the
 * editor content must be identical both times, and the second save a no-op. */
function roundTrip(html: string) {
  const pasted = editorWith(html);
  const before = withoutTrailingBlank(topLevel(pasted));
  const saved = save(pasted);

  const reopened = editorWith(documentToTiptapJSON(asDocument(saved)) as Record<string, unknown>);
  const after = withoutTrailingBlank(topLevel(reopened));
  const savedAgain = save(reopened, saved);

  expect(after.map(structure)).toEqual(before.map(structure));
  expect(allText(after)).toBe(allText(before));
  expect(sameContent(savedAgain, saved)).toBe(true);
  return saved;
}

describe("blocks nested in table cells", () => {
  it("keeps a list in a cell", () => {
    const [table] = roundTrip("<table><tr><td><p>Items:</p><ul><li><p>one</p></li><li><p>two</p></li></ul></td><td><p>x</p></td></tr></table>");
    const cell = table.table!.rows[0].cells[0];
    expect(cell.blocks!.map((block) => block.type)).toEqual(["paragraph", "list"]);
    expect(cell.blocks![1].listItems!.map((item) => item.inline[0].text)).toEqual(["one", "two"]);
    expect(cell.inline).toEqual([{ text: "Items:\none\ntwo", marks: [] }]);
    expect(table.table!.rows[0].cells[1].blocks).toBeNull();
  });

  it("keeps code in a cell", () => {
    const [table] = roundTrip('<table><tr><td><pre><code class="language-python">print(1)\nprint(2)</code></pre></td></tr></table>');
    const [code] = table.table!.rows[0].cells[0].blocks!;
    expect(code).toMatchObject({ type: "code_block", content: "print(1)\nprint(2)", language: "python" });
  });

  it("keeps a picture in a cell", () => {
    const [table] = roundTrip(`<table><tr><td><p>Chart</p><img src="${PNG}" alt="Sales chart"></td></tr></table>`);
    const [, image] = table.table!.rows[0].cells[0].blocks!;
    expect(image).toMatchObject({ type: "image", image: { src: PNG, alt: "Sales chart" } });
  });

  it("keeps several paragraphs, headings and quotes in a cell", () => {
    const [table] = roundTrip("<table><tr><td><h3>Title</h3><p>first</p><p>second</p><blockquote><p>q</p></blockquote></td></tr></table>");
    expect(table.table!.rows[0].cells[0].blocks!.map((block) => block.type)).toEqual(["heading", "paragraph", "paragraph", "quote"]);
  });

  it("keeps a table in a cell, with a list inside it", () => {
    const [table] = roundTrip("<table><tr><td><table><tr><td><ol><li><p>deep</p></li></ol></td></tr></table></td></tr></table>");
    const inner = table.table!.rows[0].cells[0].blocks![0];
    expect(inner.type).toBe("table");
    expect(inner.table!.rows[0].cells[0].blocks![0]).toMatchObject({ type: "list", ordered: true });
  });

  it("keeps a column's alignment when its cells hold blocks", () => {
    const [table] = roundTrip('<table><tr><td><p style="text-align: center">a</p><ul><li><p>b</p></li></ul></td></tr><tr><td><p style="text-align: center">c</p></td></tr></table>');
    expect(table.table!.alignments).toEqual(["center"]);
  });
});

describe("blocks nested in list items and quotes", () => {
  it("keeps code under a list item", () => {
    const [list] = roundTrip("<ul><li><p>Run:</p><pre><code>make</code></pre></li><li><p>Done</p></li></ul>");
    expect(list.listItems!.map((item) => item.inline[0].text)).toEqual(["Run:", "Done"]);
    expect(list.listItems![0].blocks).toMatchObject([{ type: "code_block", content: "make" }]);
    expect(list.content).toBe("Run:\nmake\nDone");
  });

  it("keeps extra paragraphs and a picture in a list item", () => {
    const [list] = roundTrip(`<ol><li><p>first</p><p>more of the first</p><img src="${PNG}" alt="x"></li></ol>`);
    expect(list.listItems![0].blocks!.map((block) => block.type)).toEqual(["paragraph", "image"]);
  });

  it("keeps a list in a quote", () => {
    const [quote] = roundTrip("<blockquote><p>Note:</p><ol><li><p>a</p></li><li><p>b</p></li></ol></blockquote>");
    expect(quote.type).toBe("quote");
    expect(quote.children!.map((child) => child.type)).toEqual(["paragraph", "list"]);
    expect(quote.content).toBe("Note:\na\nb");
  });

  it("keeps a quote of several paragraphs as paragraphs", () => {
    const [quote] = roundTrip("<blockquote><p>one</p><p>two</p></blockquote>");
    expect(quote.children!.map((child) => child.content)).toEqual(["one", "two"]);
  });

  it("keeps a one-paragraph quote in the classic shape", () => {
    const [quote] = roundTrip("<blockquote><p>just <strong>one</strong></p></blockquote>");
    expect(quote.children).toBeNull();
    expect(quote.inline).toEqual([
      { text: "just ", marks: [] },
      { text: "one", marks: [expect.objectContaining({ type: "bold" })] },
    ]);
  });
});

describe("nested lists", () => {
  it("nests a sub-list of the same kind as deeper levels", () => {
    const [list] = roundTrip("<ul><li><p>a</p><ul><li><p>a1</p><ul><li><p>a1x</p></li></ul></li></ul></li><li><p>b</p></li></ul>");
    expect(list.listItems!.map((item) => [item.inline[0].text, item.level, item.blocks])).toEqual([
      ["a", 0, null],
      ["a1", 1, null],
      ["a1x", 2, null],
      ["b", 0, null],
    ]);
  });

  it("keeps a sub-list of another kind as its own list", () => {
    const [list] = roundTrip("<ul><li><p>steps</p><ol><li><p>one</p></li><li><p>two</p></li></ol></li></ul>");
    expect(list.ordered).toBe(false);
    expect(list.listItems).toHaveLength(1);
    expect(list.listItems![0].blocks![0]).toMatchObject({ type: "list", ordered: true });
  });

  it("keeps a checklist inside a bullet list and a bullet list inside a checklist", () => {
    const html =
      '<ul><li><p>plan</p><ul data-type="taskList"><li data-type="taskItem" data-checked="true"><p>done</p></li></ul></li></ul>' +
      '<ul data-type="taskList"><li data-type="taskItem" data-checked="false"><p>todo</p><ul><li><p>note</p></li></ul></li></ul>';
    const [bullets, tasks] = roundTrip(html);
    expect(bullets.listItems![0].blocks![0].listItems![0]).toMatchObject({ checked: true });
    expect(tasks.listItems![0]).toMatchObject({ checked: false });
    expect(tasks.listItems![0].blocks![0].listItems![0]).toMatchObject({ checked: null });
  });

  it("keeps text that follows a sub-list inside the same item", () => {
    const [list] = roundTrip("<ul><li><p>a</p><ul><li><p>a1</p></li></ul><p>after the sub-list</p></li></ul>");
    expect(list.listItems![0].blocks!.map((block) => block.type)).toEqual(["list", "paragraph"]);
  });

  it("keeps where a numbered list starts and how it counts", () => {
    const [list] = roundTrip('<ol start="5" type="a"><li><p>e</p></li><li><p>f</p></li></ol>');
    expect(list.numbering).toEqual({ start: 5, format: "lowerLetter", levels: null });
    const [roman] = roundTrip('<ol type="I"><li><p>x</p></li></ol>');
    expect(roman.numbering).toEqual({ start: 1, format: "upperRoman", levels: null });
    const [plain] = roundTrip("<ol><li><p>x</p></li></ol>");
    expect(plain.numbering).toBeNull();
  });

  it("keeps a nested numbered list with its own start", () => {
    const [list] = roundTrip('<ol><li><p>a</p><ol start="3"><li><p>c</p></li></ol></li></ol>');
    expect(list.listItems).toHaveLength(1);
    expect(list.listItems![0].blocks![0].numbering).toEqual({ start: 3, format: "decimal", levels: null });
  });
});

describe("pasted rich content", () => {
  it("keeps every word of a Word-like paste with nesting everywhere", () => {
    const html = `
      <h1>Report</h1>
      <p>Intro with <a href="https://example.com">a link</a> and <em>emphasis</em>.</p>
      <table>
        <tr><th><p>Item</p></th><th><p>Details</p></th></tr>
        <tr><td><p>Setup</p></td><td><ul><li><p>install</p></li><li><p>configure</p><pre><code>npm ci</code></pre></li></ul></td></tr>
        <tr><td><p>Chart</p></td><td><img src="${PNG}" alt="Chart"><p>Figure 1</p></td></tr>
      </table>
      <blockquote><p>Remember:</p><ul><li><p>back up</p></li></ul><pre><code>tar czf b.tgz .</code></pre></blockquote>
      <ol start="3"><li><p>third</p><blockquote><p>quoted in an item</p></blockquote></li></ol>`;
    const saved = roundTrip(html);
    expect(saved.map((element) => element.type)).toEqual(["heading", "paragraph", "table", "quote", "list"]);
  });

  it("gives nested blocks stable ids so an unchanged document isn't saved again", () => {
    const editor = editorWith("<table><tr><td><p>a</p><ul><li><p>b</p></li></ul></td></tr></table>");
    const { elements: first, nodeIds } = reconcileWithIds(topLevel(editor) as Record<string, unknown>[], []);
    // What autosave does next (syncElementIds): the top-level node takes the id it was saved under.
    const withIds = topLevel(editor).map((node, index) => ({ ...node, attrs: { ...node.attrs, elementId: nodeIds[index] } }));
    const second = reconcileWithIds(withIds as Record<string, unknown>[], first).elements;
    expect(second).toEqual(first);
  });

  it("keeps the ids of nested blocks the server returned", () => {
    const editor = editorWith("<blockquote><p>a</p><p>b</p></blockquote>");
    const saved = save(editor);
    const fromServer = saved.map((element) => ({ ...element, children: element.children!.map((child) => ({ ...child, styleRef: "Paragraph" })) }));
    const reopened = editorWith(documentToTiptapJSON(asDocument(fromServer)) as Record<string, unknown>);
    const again = save(reopened, fromServer);
    expect(again[0].children!.map((child) => [child.id, child.styleRef])).toEqual(fromServer[0].children!.map((child) => [child.id, "Paragraph"]));
  });
});

describe("content the model can't store stops the save", () => {
  const paragraph = (content: Json[]): Json => ({ type: "paragraph", content });

  it.each([
    ["a top-level block", [{ type: "mention" }]],
    ["a block in a cell", [{ type: "table", content: [{ type: "tableRow", content: [{ type: "tableCell", content: [{ type: "video" }] }] }] }]],
    ["a block in a list item", [{ type: "bulletList", content: [{ type: "listItem", content: [paragraph([]), { type: "chart" }] }] }]],
    ["a block in a quote", [{ type: "blockquote", content: [paragraph([]), { type: "embed" }] }]],
    ["an inline node", [paragraph([{ type: "emoji", attrs: { name: "smile" } }])]],
    ["a mark", [paragraph([{ type: "text", text: "x", marks: [{ type: "highlight" }] }])]],
    ["a list numbered past the limit", [{ type: "orderedList", attrs: { start: 10_000_000 }, content: [{ type: "listItem", content: [paragraph([])] }] }]],
  ])("%s", (_, content) => {
    expect(() => reconcileWithIds(content as Record<string, unknown>[], [])).toThrow(UnsupportedContentError);
  });

  it("maps every node and mark the editor's schema has", () => {
    const schema = getSchema(editorExtensions);
    const structural = new Set(["doc", "text", "hardBreak", "listItem", "taskItem", "tableRow", "tableCell", "tableHeader"]);
    const blocks = Object.keys(schema.nodes).filter((name) => !structural.has(name));
    for (const name of blocks) {
      const node = schema.nodes[name].createAndFill();
      expect(node, name).not.toBeNull();
      expect(() => reconcileWithIds([node!.toJSON()], []), name).not.toThrow();
    }
    for (const name of Object.keys(schema.marks)) {
      const text = schema.text("x", [schema.marks[name].create(name === "link" ? { href: "https://example.com" } : name === "textStyle" ? { color: "#FF0000" } : {})]);
      const paragraphNode = schema.nodes.paragraph.create(null, text);
      expect(() => reconcileWithIds([paragraphNode.toJSON()], []), name).not.toThrow();
    }
  });
});
