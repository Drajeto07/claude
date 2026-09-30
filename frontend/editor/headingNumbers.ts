import { type Editor, Extension } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

import { Counters, itemLabel, listLevels } from "@/editor/listLabels";
import type { HeadingNumbering, ListNumbering } from "@/types/document";

/**
 * Each heading's number on the pages, as Word and both exports number them (tracker
 * DOCX-016A): the document's heading numbering counted over its headings in order, so
 * a heading moved or added here is numbered where it is now. The rules mirror the
 * backend's list_numbering.heading_labels. A heading Word doesn't number (a Title)
 * keeps `numbered: false`. A plugin sets each heading's data-number (drawn by
 * globals.css before its text); nothing of it is saved.
 */

const WORD_LEVELS = 9;

declare module "@tiptap/core" {
  interface Storage {
    headingNumbers: { numbering: HeadingNumbering | null };
  }
}

/** Each numbered heading's number, by its position in the document. */
export function headingLabels(doc: ProseMirrorNode, numbering: HeadingNumbering | null | undefined): Map<number, string> {
  const labels = new Map<number, string>();
  if (!numbering || numbering.levels.length === 0) return labels;
  const own = { start: numbering.levels[0].start, format: numbering.levels[0].format, levels: numbering.levels } as ListNumbering;
  const levels = listLevels("number", own);
  const counters = new Counters(levels.map((level) => level.start), levels.map((level) => level.restart));
  doc.forEach((node, position) => {
    if (node.type.name !== "heading" || node.attrs.numbered === false) return;
    const index = Math.min(Math.max(Number(node.attrs.level) || 1, 1), WORD_LEVELS) - 1;
    const format = numbering.levels[index]?.format;
    if (!format || format === "bullet" || format === "none") return;
    const label = itemLabel(levels, counters, index).trim();
    if (label) labels.set(position, label);
  });
  return labels;
}

/** Whether a heading is numbered: false for one Word doesn't number; kept, never drawn. */
export const HeadingNumberedAttribute = Extension.create({
  name: "headingNumbered",
  addGlobalAttributes() {
    return [{ types: ["heading"], attributes: { numbered: { default: null, rendered: false } } }];
  },
});

const headingNumbersKey = new PluginKey<DecorationSet>("headingNumbers");

/** The document's heading numbering, for the pages to be numbered with (set from the document as it changes). */
export function setHeadingNumbering(editor: Editor, numbering: HeadingNumbering | null | undefined) {
  if (editor.isDestroyed) return;
  editor.storage.headingNumbers.numbering = numbering ?? null;
  editor.view.dispatch(editor.state.tr.setMeta(headingNumbersKey, true));
}

export const HeadingNumbers = Extension.create<Record<string, never>, { numbering: HeadingNumbering | null }>({
  name: "headingNumbers",
  addStorage() {
    return { numbering: null };
  },
  addProseMirrorPlugins() {
    const storage = this.storage;
    const decorate = (doc: ProseMirrorNode) =>
      DecorationSet.create(
        doc,
        [...headingLabels(doc, storage.numbering)].map(([position, label]) =>
          Decoration.node(position, position + doc.nodeAt(position)!.nodeSize, { "data-number": label }),
        ),
      );
    return [
      new Plugin<DecorationSet>({
        key: headingNumbersKey,
        state: {
          init: (_, state) => decorate(state.doc),
          apply: (tr, set) => (tr.docChanged || tr.getMeta(headingNumbersKey) ? decorate(tr.doc) : set),
        },
        props: { decorations: (state) => headingNumbersKey.getState(state) },
      }),
    ];
  },
});
