import { Node, mergeAttributes } from "@tiptap/core";

/**
 * A real Tiptap node for ElementType.PAGE_BREAK -- an atomic (no editable
 * content), selectable block, not a styled empty paragraph standing in for
 * one. Deliberately does NOT declare its own `elementId` attribute -- like
 * every other node type, it picks that up from elementId.ts's global
 * attribute (this node's name is added to that extension's `types` list),
 * so a page break can be selected, mapped back to its source Element, and
 * deleted like anything else (Backspace/Delete on a selected atom node
 * removes it -- Tiptap's built-in behaviour, no custom keymap needed).
 */
export const PageBreak = Node.create({
  name: "pageBreak",
  group: "block",
  atom: true,
  selectable: true,
  draggable: false,

  parseHTML() {
    return [{ tag: 'div[data-page-break="true"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, { "data-page-break": "true", contenteditable: "false" }),
      ["div", { class: "page-break-label" }, "Page break"],
    ];
  },
});
