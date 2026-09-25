import { Extension } from "@tiptap/core";
import { Plugin } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

export type ChangeKind = "added" | "removed" | "moved" | "retyped" | "edited";

/**
 * Marks the blocks that changed between two versions (before/after): each
 * top-level node whose element id is in `changes` gets `data-change="<kind>"`,
 * as a decoration, so ProseMirror's own rendering is left alone. Styled in
 * globals.css under .document-preview.
 */
export const ChangeHighlight = Extension.create<{ changes: Record<string, ChangeKind> }>({
  name: "changeHighlight",

  addOptions() {
    return { changes: {} };
  },

  addProseMirrorPlugins() {
    const { changes } = this.options;
    return [
      new Plugin({
        props: {
          decorations(state) {
            const decorations: Decoration[] = [];
            state.doc.forEach((node, offset) => {
              const kind = changes[node.attrs.elementId as string];
              if (kind) decorations.push(Decoration.node(offset, offset + node.nodeSize, { "data-change": kind }));
            });
            return DecorationSet.create(state.doc, decorations);
          },
        },
      }),
    ];
  },
});
