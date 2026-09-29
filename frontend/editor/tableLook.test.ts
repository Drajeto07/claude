import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Document, Element, TableCell, TableContent, TableRow } from "@/types/document";

import { documentToTiptapJSON } from "./documentToTiptap";
import { editorExtensions } from "./extensions";
import { reconcileWithIds } from "./tiptapToDocument";

/**
 * A Word table's geometry and look in the editor (tracker DOCX-017): it comes back from
 * the editor as it went in, and the pages draw it -- each cell edge's border as Word
 * resolves it, cell margins, vertical alignment, row heights, column widths.
 */

const editors: Editor[] = [];

afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

const LINE = "solid 0.5pt #000000";

function cell(text: string, extra: Partial<TableCell> = {}): TableCell {
  return {
    id: crypto.randomUUID(),
    inline: [{ text, marks: [] }],
    header: false,
    colspan: 1,
    rowspan: 1,
    background: null,
    blocks: null,
    verticalAlign: null,
    align: null,
    borders: null,
    margins: null,
    ...extra,
  };
}

function row(cells: TableCell[], extra: Partial<TableRow> = {}): TableRow {
  return { id: crypto.randomUUID(), cells, heightCm: null, heightRule: "atLeast", repeatHeader: false, ...extra };
}

const WORD_TABLE: TableContent = {
  rows: [
    row([cell("Item", { header: true }), cell("Price", { header: true })], { repeatHeader: true }),
    row(
      [
        cell("Paper", { align: "right" }),
        cell("12.50", { verticalAlign: "center", borders: { top: null, bottom: "double 1.5pt #C00000", left: null, right: null }, margins: { topCm: 0.1, bottomCm: null, leftCm: null, rightCm: null } }),
      ],
      { heightCm: 1.5, heightRule: "exact" },
    ),
  ],
  hasHeaderRow: true,
  alignments: null, // its columns' cells differ: "Paper" keeps its own
  columnWidthsCm: [2, 8],
  widthCm: null,
  widthPercent: null,
  align: "center",
  indentCm: null,
  borders: { top: LINE, bottom: LINE, left: LINE, right: LINE, insideH: LINE, insideV: "none" },
  cellMargins: { topCm: 0, bottomCm: 0, leftCm: 0.3, rightCm: 0.3 },
  style: "Table Grid",
  look: { firstRow: true, lastRow: false, firstColumn: true, lastColumn: false, bandedRows: true, bandedColumns: false },
  headerBold: false,
};

function tableElement(table: TableContent): Element {
  return {
    id: crypto.randomUUID(),
    type: "table",
    content: "",
    inline: null,
    listItems: null,
    ordered: false,
    table,
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
  } as Element;
}

function open(table: TableContent) {
  const element = tableElement(table);
  const document = { elements: [element], resolvedStyles: {}, settings: {} } as unknown as Document;
  const editor = new Editor({ extensions: editorExtensions, content: documentToTiptapJSON(document) });
  editors.push(editor);
  return { editor, element };
}

describe("a Word table in the editor", () => {
  it("comes back as it went in", () => {
    const { editor, element } = open(WORD_TABLE);

    const { elements: saved } = reconcileWithIds((editor.getJSON().content ?? []) as Record<string, unknown>[], [element]);

    const strip = (table: TableContent) => JSON.parse(JSON.stringify(table, (key, value) => (key === "id" ? undefined : value)));
    expect(strip(saved[0].table!)).toEqual(strip(WORD_TABLE));
  });

  it("is drawn as Word draws it", () => {
    const { editor } = open(WORD_TABLE);
    const dom = editor.view.dom;

    expect(dom.querySelector(".tableWrapper")?.classList.contains("word-table")).toBe(true);
    const cols = [...dom.querySelectorAll("col")].map((col) => (col as HTMLElement).style.width);
    expect(cols).toEqual(["76px", "302px"]); // 2 and 8 cm
    const [item, price, paper, amount] = [...dom.querySelectorAll("th, td")] as HTMLElement[];
    expect(item.style.borderTop).toBe("0.5pt solid rgb(0, 0, 0)");
    expect(price.style.borderLeftStyle).toBe("none"); // the table has no lines between its columns
    expect(paper.style.borderTop).toBe("0.5pt solid rgb(0, 0, 0)"); // the line between its rows
    expect(amount.style.borderBottom).toBe("1.5pt double rgb(192, 0, 0)");
    expect(amount.style.verticalAlign).toBe("middle");
    expect(amount.style.padding).toBe("0.1cm 0.3cm 0cm");
    expect((dom.querySelectorAll("tr")[1] as HTMLElement).style.height).toBe("1.5cm");
  });

  it("leaves a table made here as the editor draws it", () => {
    const plain: TableContent = {
      ...WORD_TABLE,
      columnWidthsCm: null,
      align: null,
      borders: null,
      cellMargins: null,
      style: null,
      look: null,
      headerBold: true,
      rows: [row([cell("a")]), row([cell("b")])],
      hasHeaderRow: false,
      alignments: null,
    };
    const { editor, element } = open(plain);

    expect(editor.view.dom.querySelector(".word-table")).toBeNull();
    const { elements: saved } = reconcileWithIds((editor.getJSON().content ?? []) as Record<string, unknown>[], [element]);
    expect(saved[0].table).toMatchObject({ style: null, borders: null, headerBold: true, columnWidthsCm: null });
  });
});
