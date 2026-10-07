import { Extension } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

import type { ListNumberingAttr } from "@/editor/listNumbering";
import type { ListNumbering } from "@/types/document";
import { CYRILLIC, moreFormat } from "./numberFormats";
import { onlyTextChanged } from "./textEdit";

/**
 * Each list item's label on the pages, as Word and both exports number it (tracker
 * DOCX-016): "Чл. 1.", "а)", "1.1.1.", 01, the list's own bullets -- and 1., a., i. or
 * •, ◦, ▪ where a list has no levels of its own. The rules mirror the backend's
 * app/formatting/list_numbering.py. A plugin sets each item's data-label (drawn by
 * globals.css in place of the browser's marker), and a list with its own levels
 * gets their indents. Nothing of it is saved: the numbering is the list's.
 */

const WORD_LEVELS = 9;
const LEVEL_INDENT_TWIPS = 357;
const DEFAULT_FORMATS = ["decimal", "lowerLetter", "lowerRoman"];
const DEFAULT_BULLETS = ["•", "◦", "▪"];
const ROMAN: [number, string][] = [
  [1000, "m"], [900, "cm"], [500, "d"], [400, "cd"], [100, "c"], [90, "xc"],
  [50, "l"], [40, "xl"], [10, "x"], [9, "ix"], [5, "v"], [4, "iv"], [1, "i"],
];
const TWIPS_PER_PX = 15;

/** A number as Word shows it: letters a..z then aa, bb..; Roman numerals to 3999; 01..09;
 * Cyrillic а..я then аа..; their capital forms; Word's other styles (numberFormats.ts: 1st, ①,
 * 一, א ...); any other number as it is. */
export function formatListNumber(value: number, format: string | null | undefined): string {
  if ((format === "lowerLetter" || format === "upperLetter") && value > 0) {
    const text = String.fromCharCode(97 + ((value - 1) % 26)).repeat(Math.floor((value - 1) / 26) + 1);
    return format === "upperLetter" ? text.toUpperCase() : text;
  }
  if ((format === "russianLower" || format === "russianUpper") && value > 0) {
    const text = CYRILLIC[(value - 1) % CYRILLIC.length].repeat(Math.floor((value - 1) / CYRILLIC.length) + 1);
    return format === "russianUpper" ? text.toUpperCase() : text;
  }
  if ((format === "lowerRoman" || format === "upperRoman") && value > 0 && value < 4000) {
    let rest = value;
    let text = "";
    for (const [amount, letters] of ROMAN) {
      while (rest >= amount) {
        text += letters;
        rest -= amount;
      }
    }
    return format === "upperRoman" ? text.toUpperCase() : text;
  }
  if (format === "decimalZero" && value >= 0 && value < 10) return `0${value}`;
  return (format && moreFormat(value, format)) ?? String(value);
}

/** A level's label: %n as level n's number in its format (1, 2, 3 with legal numbering). */
export function levelLabel(text: string, values: number[], formats: string[], legal = false): string {
  return text.replace(/%([1-9])/g, (_, digit: string) => {
    const index = Number(digit) - 1;
    return index < values.length ? formatListNumber(values[index], legal ? "decimal" : formats[index]) : "";
  });
}

/** A list's counters: an item advances its level and starts again the levels below it --
 * after any level above (Word's default), never (restart 0), or only after level n. */
export class Counters {
  readonly values: number[];

  constructor(
    private readonly starts: number[],
    private readonly restarts: (number | null)[],
  ) {
    this.values = starts.map((start) => start - 1);
  }

  advance(level: number): number[] {
    this.values[level] += 1;
    for (let deeper = level + 1; deeper < this.values.length; deeper += 1) {
      let restart = this.restarts[deeper];
      if (restart !== null && restart > 0 && restart - 1 >= deeper) restart = null; // Word ignores it
      if (restart === null || (restart > 0 && level <= restart - 1)) this.values[deeper] = this.starts[deeper] - 1;
    }
    return this.values.slice(0, level + 1);
  }
}

export type Level = { format: string; text: string; start: number; left: number; hanging: number; legal: boolean; restart: number | null };

/** A list's nine Word levels: its own from `baseLevel`, the usual ones elsewhere (as list_numbering.list_levels). */
export function listLevels(kind: "number" | "bullet", numbering: ListNumbering | null, baseLevel = 0): Level[] {
  const own = numbering?.levels ?? [];
  return Array.from({ length: WORD_LEVELS }, (_, level) => {
    const left = LEVEL_INDENT_TWIPS * (level + 1);
    const index = level - baseLevel;
    const mine = index >= 0 && index < own.length ? own[index] : null;
    if (!mine) {
      const format = kind === "bullet" ? "bullet" : index === 0 && numbering ? numbering.format : DEFAULT_FORMATS[level % 3];
      const text = kind === "bullet" ? DEFAULT_BULLETS[level % 3] : `%${level + 1}.`;
      return { format, text, start: 1, left, hanging: LEVEL_INDENT_TWIPS, legal: false, restart: null };
    }
    const format = kind === "number" && index === 0 && mine.format !== "bullet" && mine.format !== "none" ? numbering!.format : mine.format;
    const text =
      format === "bullet"
        ? mine.text || DEFAULT_BULLETS[level % 3]
        : (mine.text ?? `%${index + 1}.`).replace(/%([1-9])/g, (_, digit: string) => `%${Math.min(Number(digit) + baseLevel, WORD_LEVELS)}`);
    return {
      format,
      text,
      start: mine.start,
      left: mine.indentCm != null ? Math.round(mine.indentCm * 566.929) : left,
      hanging: mine.hangingCm != null ? Math.round(mine.hangingCm * 566.929) : LEVEL_INDENT_TWIPS,
      legal: mine.legal,
      restart: mine.restartAfter ? mine.restartAfter + baseLevel : mine.restartAfter,
    };
  });
}

/** The label of the next item at `level`. */
export function itemLabel(levels: Level[], counters: Counters, level: number): string {
  const values = counters.advance(level);
  const spec = levels[level];
  return spec.format === "bullet" ? spec.text : levelLabel(spec.text, values, levels.map((each) => each.format), spec.legal);
}

const FORMAT_BY_TYPE: Record<string, ListNumbering["format"]> = { "1": "decimal", a: "lowerLetter", A: "upperLetter", i: "lowerRoman", I: "upperRoman" };
const LIST_KINDS: Record<string, "number" | "bullet"> = { orderedList: "number", bulletList: "bullet" };

/** A list node's numbering, as tiptapToDocument.ts numberingOf reads it (null: the usual). */
function numberingOfNode(list: ProseMirrorNode): ListNumbering | null {
  const own = (list.attrs.numbering ?? null) as ListNumberingAttr | null;
  const levels = own?.levels ?? null;
  if (list.type.name === "bulletList") return levels ? { start: 1, format: "decimal", levels } : null;
  const start = Number(list.attrs.start ?? 1) || 1;
  const type = list.attrs.type as string | null | undefined;
  const format = type ? (FORMAT_BY_TYPE[type] ?? "decimal") : (own?.format ?? "decimal");
  return start === 1 && format === "decimal" && !levels ? null : { start, format, levels };
}

function labelList(list: ProseMirrorNode, pos: number, baseLevel: number, into: Decoration[]) {
  const kind = LIST_KINDS[list.type.name];
  if (!kind) return; // a checklist: its checkboxes lead
  const numbering = numberingOfNode(list);
  const levels = listLevels(kind, numbering, Math.min(baseLevel, WORD_LEVELS - 1));
  const starts = levels.map((level) => level.start);
  if (kind === "number" && numbering) starts[Math.min(baseLevel, WORD_LEVELS - 1)] = numbering.start;
  const counters = new Counters(starts, levels.map((level) => level.restart));
  const own = Boolean(numbering?.levels);
  const indent = (level: number) => (own ? { style: `padding-left:${Math.max(0, (levels[level].left - (level > baseLevel ? levels[level - 1].left : 0)) / TWIPS_PER_PX)}px` } : null);
  const top = indent(Math.min(baseLevel, WORD_LEVELS - 1));
  if (top) into.push(Decoration.node(pos, pos + list.nodeSize, top));
  labelItems(list, pos, Math.min(baseLevel, WORD_LEVELS - 1), levels, counters, indent, into);
}

function labelItems(
  list: ProseMirrorNode,
  pos: number,
  level: number,
  levels: Level[],
  counters: Counters,
  indent: (level: number) => { style: string } | null,
  into: Decoration[],
) {
  list.forEach((item, offset) => {
    const itemPos = pos + 1 + offset;
    const attrs: Record<string, string> = { "data-label": itemLabel(levels, counters, level) };
    if (isPictureItem(item)) attrs["data-picture-item"] = "";
    into.push(Decoration.node(itemPos, itemPos + item.nodeSize, attrs));
    // A sub-list at the end of the item that counts like its list is its next level (as tiptapToDocument.ts nestsAsLevels).
    const last = item.lastChild;
    const nests = last !== null && last !== item.firstChild && last.type === list.type && numberingOfNode(last) === null;
    item.forEach((child, childOffset) => {
      const childPos = itemPos + 1 + childOffset;
      if (child === last && nests && level + 1 < WORD_LEVELS) {
        const deeper = indent(level + 1);
        if (deeper) into.push(Decoration.node(childPos, childPos + child.nodeSize, deeper));
        labelItems(child, childPos, level + 1, levels, counters, indent, into);
      } else if (LIST_KINDS[child.type.name]) {
        labelList(child, childPos, level + 1, into); // a list of its own under the item's text
      } else {
        labelWithin(child, childPos, into);
      }
    });
  });
}

/**
 * An item that is its paragraph and a picture in line with the text (DOCX-027A): while the
 * paragraph is empty, globals.css draws the label beside the picture, on its bottom line, as
 * Word sets a picture in the item's paragraph -- the empty paragraph kept, to type in. Whether
 * it is empty is CSS's to see, so typing (which maps these labels, never redoes them) changes it.
 */
function isPictureItem(item: ProseMirrorNode): boolean {
  if (item.childCount !== 2 || item.child(0).type.name !== "paragraph" || item.child(1).type.name !== "image") return false;
  const picture = item.child(1).attrs.picture as { placement?: { side?: string | null } | null } | null;
  return !picture?.placement?.side;
}

/** The lists inside a block (a quote, a table), each numbered on its own. */
function labelWithin(node: ProseMirrorNode, pos: number, into: Decoration[]) {
  node.descendants((child, offset) => {
    if (!LIST_KINDS[child.type.name]) return true; // a checklist's items may hold lists too
    labelList(child, pos + 1 + offset, 0, into);
    return false;
  });
}

/** Every list item's label in the document, as decorations. */
export function listLabelDecorations(doc: ProseMirrorNode): Decoration[] {
  const into: Decoration[] = [];
  labelWithin(doc, -1, into);
  return into;
}

const listLabelsKey = new PluginKey<DecorationSet>("listLabels");

export const ListLabels = Extension.create({
  name: "listLabels",
  addProseMirrorPlugins() {
    return [
      new Plugin<DecorationSet>({
        key: listLabelsKey,
        state: {
          init: (_, state) => DecorationSet.create(state.doc, listLabelDecorations(state.doc)),
          // Typing in a paragraph moves the labels along, never changes them (PERF-005).
          apply: (tr, set) => (onlyTextChanged(tr) ? set.map(tr.mapping, tr.doc) : tr.docChanged ? DecorationSet.create(tr.doc, listLabelDecorations(tr.doc)) : set),
        },
        props: {
          decorations: (state) => listLabelsKey.getState(state),
        },
      }),
    ];
  },
});
