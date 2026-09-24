import { Node, mergeAttributes } from "@tiptap/core";

/**
 * A real Tiptap node for ElementType.CAPTION -- distinct from `paragraph` so
 * a caption round-trips through editor reconciliation instead of silently
 * downgrading to a plain paragraph (and losing its DOCX "Caption" style on
 * export) the moment the document autosaves. Schema-identical to Tiptap's
 * own Paragraph node (inline content, no restricted marks) other than the
 * node name and its parseHTML/renderHTML tag attribute.
 */
export const Caption = Node.create({
  name: "caption",
  group: "block",
  content: "inline*",

  parseHTML() {
    return [{ tag: 'p[data-caption="true"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["p", mergeAttributes(HTMLAttributes, { "data-caption": "true" }), 0];
  },
});
