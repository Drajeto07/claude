import { Extension } from "@tiptap/core";

/**
 * Renders the `style` node attr (built by documentToTiptap.ts from
 * Document.resolvedStyles, computed by the Phase 4 formatting engine) as a
 * real inline `style="..."` HTML attribute. Kept separate from
 * ConfidenceIndicator -- two independent concerns that happen to use the
 * same addGlobalAttributes mechanism.
 */
export const AppliedStyle = Extension.create({
  name: "appliedStyle",
  addGlobalAttributes() {
    return [
      {
        types: ["heading", "paragraph", "blockquote", "codeBlock", "bulletList", "orderedList", "taskList", "table", "image", "horizontalRule", "caption", "footnote"],
        attributes: {
          style: {
            default: null,
            renderHTML: (attributes: Record<string, unknown>) => {
              const style = attributes.style as string | null | undefined;
              return style ? { style } : {};
            },
            parseHTML: (element: HTMLElement) => element.getAttribute("style"),
          },
        },
      },
    ];
  },
});
