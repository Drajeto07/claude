import { Extension } from "@tiptap/core";

/**
 * Renders the `elementId` node attr (set in documentToTiptap.ts from the
 * backend Element.id) as `data-element-id`, so a DOM node can be mapped back
 * to its source Element. Used by OutlinePanel's click-to-scroll today;
 * reusable by a future Properties panel that needs the same mapping.
 */
export const ElementId = Extension.create({
  name: "elementId",
  addGlobalAttributes() {
    return [
      {
        types: ["heading", "paragraph", "blockquote", "codeBlock", "bulletList", "orderedList", "table", "image"],
        attributes: {
          elementId: {
            default: null,
            renderHTML: (attributes: Record<string, unknown>) => {
              const elementId = attributes.elementId as string | null;
              return elementId ? { "data-element-id": elementId } : {};
            },
            parseHTML: (element: HTMLElement) => element.getAttribute("data-element-id"),
          },
        },
      },
    ];
  },
});
