import { Mark, mergeAttributes } from "@tiptap/core";

import type { Element, InlineRun } from "@/types/document";

/**
 * Word's hidden text -- the Document Model's "hidden" mark (tracker DOCX-025).
 * It is kept with the document and stays hidden: the page shows it only on
 * request ("Show hidden text" in the status bar puts `show-hidden` on the page,
 * globals.css does the rest). Typing next to it isn't hidden (not inclusive),
 * and hidden text pasted from Word (display:none) stays hidden.
 */
export const HiddenText = Mark.create({
  name: "hidden",
  inclusive: false,

  parseHTML() {
    return [
      { tag: "span[data-hidden]" },
      { style: "display", getAttrs: (value) => (String(value).trim().toLowerCase() === "none" ? null : false) },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, { "data-hidden": "", class: "hidden-text" }), 0];
  },
});

const WORD = /[\p{L}\p{N}_]+/gu;

function hiddenIn(runs: InlineRun[] | null | undefined): number {
  return (runs ?? [])
    .filter((run) => run.marks.some((mark) => mark.type === "hidden"))
    .reduce((count, run) => count + (run.text.match(WORD)?.length ?? 0), 0);
}

/** An element's text as a page shows it: without its hidden text. */
export function visibleText(element: Element): string {
  if (!element.inline) return element.content;
  return element.inline
    .filter((run) => !run.marks.some((mark) => mark.type === "hidden"))
    .map((run) => run.text)
    .join("");
}

/** How many words of the document are hidden text, nested blocks included. */
export function hiddenWordCount(elements: Element[]): number {
  let count = 0;
  for (const element of elements) {
    count += hiddenIn(element.inline);
    for (const item of element.listItems ?? []) count += hiddenIn(item.inline) + hiddenWordCount(item.blocks ?? []);
    for (const row of element.table?.rows ?? []) {
      for (const cell of row.cells) count += hiddenIn(cell.inline) + hiddenWordCount(cell.blocks ?? []);
    }
    count += hiddenWordCount(element.children ?? []);
  }
  return count;
}
