import type { Editor } from "@tiptap/react";

/** What "Translate selection" translates (TRAN-005): the top-level blocks the selection touches
 * (the cursor's block when nothing is selected) -- or, when the selection is part of one
 * paragraph-like block's text, that block and the selected characters of its text. */
export type TranslationTarget = { elementIds: string[]; selection: { start: number; end: number } | null };

export function translationTarget(editor: Editor): TranslationTarget | null {
  const { doc, selection } = editor.state;
  const { from, to, empty } = selection;
  const touched: { id: string; offset: number; textblock: boolean; text: string }[] = [];
  doc.forEach((node, offset) => {
    const end = offset + node.nodeSize;
    if (end > from && offset < Math.max(to, from + 1) && typeof node.attrs.elementId === "string") {
      touched.push({ id: node.attrs.elementId, offset, textblock: node.isTextblock, text: node.textBetween(0, node.content.size, "\n", "\n") });
    }
  });
  if (touched.length === 0) return null;
  if (!empty && touched.length === 1 && touched[0].textblock) {
    const block = touched[0];
    const start = doc.textBetween(block.offset + 1, from, "\n", "\n").length;
    const length = doc.textBetween(from, to, "\n", "\n").length;
    if (length > 0 && !(start === 0 && length >= block.text.length)) return { elementIds: [block.id], selection: { start, end: start + length } };
  }
  return { elementIds: touched.map((block) => block.id), selection: null };
}
