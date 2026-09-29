import { Extension } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

import type { TableCell, TableContent, TableRow } from "@/types/document";

/**
 * A Word table's geometry and look in the editor (tracker DOCX-017). What the model
 * holds rides on the table, its rows and its cells -- not rendered; tiptapToDocument.ts
 * gives it back on save -- and a plugin draws it: each cell edge's border as Word
 * resolves it (the cell's own, its neighbour's across the edge, else the table's), cell
 * margins, vertical alignment, row heights, where the table sits. Column widths go
 * through Tiptap's own colwidth. A table made here has none of it and the editor's look.
 */

export type TableLookAttr = Pick<
  TableContent,
  "columnWidthsCm" | "widthCm" | "widthPercent" | "align" | "indentCm" | "borders" | "cellMargins" | "style" | "look" | "headerBold"
>;
export type RowLookAttr = Pick<TableRow, "heightCm" | "heightRule" | "repeatHeader">;
export type CellLookAttr = Pick<TableCell, "verticalAlign" | "align" | "borders" | "margins">;

export const CM_TO_PX = 96 / 2.54;
const WORD_CELL_MARGIN_CM = 0.19; // Word's left and right cell margin
type Side = "top" | "bottom" | "left" | "right";

export const TableLookAttributes = Extension.create({
  name: "tableLookAttributes",
  addGlobalAttributes() {
    return [
      { types: ["table"], attributes: { look: { default: null, rendered: false } } },
      { types: ["tableRow"], attributes: { row: { default: null, rendered: false } } },
      { types: ["tableCell", "tableHeader"], attributes: { look: { default: null, rendered: false } } },
    ];
  },
});

/** A border value ("solid 0.5pt #000000", validated by the backend) as CSS. */
export function cssBorder(value: string | null | undefined): string {
  if (!value || value === "none") return "none";
  const [style, width, color] = value.split(" ");
  return `${width} ${style} ${color}`;
}

type Placed = { cell: ProseMirrorNode; pos: number; row: number; column: number; last: { row: number; column: number } };

function decorateTable(table: ProseMirrorNode, pos: number, into: Decoration[]) {
  const look = (table.attrs.look ?? null) as TableLookAttr | null;
  if (!look) return;
  const wrapper: string[] = [];
  if (look.align === "center" || look.align === "right") wrapper.push(`display:flex`, `justify-content:${look.align === "center" ? "center" : "flex-end"}`);
  if (look.indentCm) wrapper.push(`padding-left:${look.indentCm}cm`);
  into.push(Decoration.node(pos, pos + table.nodeSize, { class: "word-table", ...(wrapper.length ? { style: wrapper.join(";") } : {}) }));

  // Where each cell sits in the grid, spans taken into account.
  const placed: Placed[] = [];
  const owner = new Map<string, Placed>();
  const rows: { row: ProseMirrorNode; pos: number }[] = [];
  table.forEach((row, rowOffset) => rows.push({ row, pos: pos + 1 + rowOffset }));
  rows.forEach(({ row, pos: rowPos }, rowIndex) => {
    let column = 0;
    row.forEach((cell, cellOffset) => {
      while (owner.has(`${rowIndex}:${column}`)) column += 1;
      const colspan = Math.max(1, Number(cell.attrs.colspan) || 1);
      const rowspan = Math.max(1, Number(cell.attrs.rowspan) || 1);
      const slot: Placed = { cell, pos: rowPos + 1 + cellOffset, row: rowIndex, column, last: { row: rowIndex + rowspan - 1, column: column + colspan - 1 } };
      placed.push(slot);
      for (let dr = 0; dr < rowspan; dr += 1) for (let dc = 0; dc < colspan; dc += 1) owner.set(`${rowIndex + dr}:${column + dc}`, slot);
      column += colspan;
    });
    const height = (row.attrs.row ?? null) as RowLookAttr | null;
    if (height?.heightCm) into.push(Decoration.node(rowPos, rowPos + row.nodeSize, { style: `height:${height.heightCm}cm` }));
  });
  const lastRow = rows.length - 1;
  const lastColumn = Math.max(0, ...placed.map((slot) => slot.last.column));

  const own = (slot: Placed | undefined, side: Side) => ((slot?.cell.attrs.look ?? null) as CellLookAttr | null)?.borders?.[side] ?? null;
  const tableSide = (side: Side | "insideH" | "insideV") => look.borders?.[side] ?? null;
  for (const slot of placed) {
    const cellLook = (slot.cell.attrs.look ?? null) as CellLookAttr | null;
    const top = own(slot, "top") ?? own(owner.get(`${slot.row - 1}:${slot.column}`), "bottom") ?? tableSide(slot.row === 0 ? "top" : "insideH");
    const left = own(slot, "left") ?? own(owner.get(`${slot.row}:${slot.column - 1}`), "right") ?? tableSide(slot.column === 0 ? "left" : "insideV");
    const bottom = slot.last.row >= lastRow ? (own(slot, "bottom") ?? tableSide("bottom")) : null;
    const right = slot.last.column >= lastColumn ? (own(slot, "right") ?? tableSide("right")) : null;
    const margin = (side: Side) => {
      const cm = cellLook?.margins?.[`${side}Cm`] ?? look.cellMargins?.[`${side}Cm`] ?? (side === "left" || side === "right" ? WORD_CELL_MARGIN_CM : 0);
      return `${cm}cm`;
    };
    const style = [
      `border-top:${cssBorder(top)}`,
      `border-left:${cssBorder(left)}`,
      `border-bottom:${cssBorder(bottom)}`,
      `border-right:${cssBorder(right)}`,
      `padding:${margin("top")} ${margin("right")} ${margin("bottom")} ${margin("left")}`,
      ...(cellLook?.verticalAlign ? [`vertical-align:${cellLook.verticalAlign === "center" ? "middle" : cellLook.verticalAlign}`] : []),
    ];
    into.push(Decoration.node(slot.pos, slot.pos + slot.cell.nodeSize, { style: style.join(";") }));
  }
}

/** Every Word table's look in the document, as decorations. */
export function tableLookDecorations(doc: ProseMirrorNode): Decoration[] {
  const into: Decoration[] = [];
  doc.descendants((node, pos) => {
    if (node.type.name === "table") decorateTable(node, pos, into);
    return true; // tables inside cells too
  });
  return into;
}

const tableLookKey = new PluginKey<DecorationSet>("tableLook");

export const TableLook = Extension.create({
  name: "tableLook",
  addProseMirrorPlugins() {
    return [
      new Plugin<DecorationSet>({
        key: tableLookKey,
        state: {
          init: (_, state) => DecorationSet.create(state.doc, tableLookDecorations(state.doc)),
          apply: (tr, set) => (tr.docChanged ? DecorationSet.create(tr.doc, tableLookDecorations(tr.doc)) : set),
        },
        props: {
          decorations: (state) => tableLookKey.getState(state),
        },
      }),
    ];
  },
});

/** A table's look as the editor keeps it: null for a table made here (the model's defaults). */
export function tableLookOf(table: TableContent): TableLookAttr | null {
  const look: TableLookAttr = {
    columnWidthsCm: table.columnWidthsCm,
    widthCm: table.widthCm,
    widthPercent: table.widthPercent,
    align: table.align,
    indentCm: table.indentCm,
    borders: table.borders,
    cellMargins: table.cellMargins,
    style: table.style,
    look: table.look,
    headerBold: table.headerBold,
  };
  const plain = Object.entries(look).every(([key, value]) => (key === "headerBold" ? value === true : value === null));
  return plain ? null : look;
}

export const PLAIN_TABLE: TableLookAttr = {
  columnWidthsCm: null,
  widthCm: null,
  widthPercent: null,
  align: null,
  indentCm: null,
  borders: null,
  cellMargins: null,
  style: null,
  look: null,
  headerBold: true,
};
