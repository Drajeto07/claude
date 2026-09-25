import { Node, mergeAttributes } from "@tiptap/core";

/**
 * A real Tiptap node for ElementType.FOOTNOTE (a note the importer moved to the
 * end of the document), for the same reason as caption.ts: as a plain
 * paragraph it would be saved back as a paragraph the moment the document
 * autosaves, losing its footnote look in the editor and its "Footnote Text"
 * style in the Word export. Schema-identical to a paragraph otherwise.
 */
export const Footnote = Node.create({
  name: "footnote",
  group: "block",
  content: "inline*",

  parseHTML() {
    return [{ tag: 'p[data-footnote="true"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["p", mergeAttributes(HTMLAttributes, { "data-footnote": "true" }), 0];
  },
});
