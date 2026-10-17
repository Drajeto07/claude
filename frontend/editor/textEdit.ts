import type { Fragment } from "@tiptap/pm/model";
import type { EditorState, Transaction } from "@tiptap/pm/state";
import { AddMarkStep, RemoveMarkStep, ReplaceStep } from "@tiptap/pm/transform";

/**
 * Whether a transaction only typed, deleted or restyled text inside paragraphs and headings
 * (tracker PERF-005): every step a replacement of text by text within one textblock -- no
 * block made, split, joined or removed, no picture or other inline node in or out -- or a mark
 * added or removed. What the editor draws from the blocks themselves (list labels, heading
 * numbers, pictures' and tables' looks) stays as it was then, only moved along: the plugins
 * keep their decorations mapped instead of building them again from the whole document, and
 * the page layout can wait for a pause in the typing.
 */
export function onlyTextChanged(tr: Transaction): boolean {
  if (!tr.docChanged) return false;
  return tr.steps.every((step, index) => {
    if (step instanceof AddMarkStep || step instanceof RemoveMarkStep) return true;
    if (!(step instanceof ReplaceStep)) return false;
    const { from, to, slice } = step as unknown as { from: number; to: number; slice: { openStart: number; openEnd: number; content: Fragment } };
    if (slice.openStart !== 0 || slice.openEnd !== 0) return false;
    let textOnly = true;
    slice.content.forEach((node) => {
      if (!node.isText) textOnly = false;
    });
    if (!textOnly) return false;
    const doc = tr.docs[index];
    const start = doc.resolve(from);
    if (!start.parent.isTextblock || start.parent !== doc.resolve(to).parent) return false;
    let removesNodes = false;
    if (to > from) {
      doc.nodesBetween(from, to, (node) => {
        if (node !== start.parent && !node.isText) removesNodes = true;
        return !removesNodes;
      });
    }
    return !removesNodes;
  });
}

// The states typing made (onlyTextChanged), noted by the plugins that lay the pages out.
const typed = new WeakSet<EditorState>();

/** Notes that `state` came of typing, when `tr` only changed text. */
export function noteTyping(tr: Transaction, state: EditorState): void {
  if (onlyTextChanged(tr)) typed.add(state);
}

/** How long to wait before laying the pages out again: a pause in the typing, or `delay`. */
export function layoutDelay(state: EditorState, delay: number): number {
  return typed.has(state) ? TYPING_PAUSE_MS : delay;
}

// While a person types, the page layout waits for this much of a pause (a whole document's
// worth of measuring between two keystrokes is what made typing slow, PERF-005).
export const TYPING_PAUSE_MS = 300;
