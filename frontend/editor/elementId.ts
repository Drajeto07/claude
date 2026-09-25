import { Extension } from "@tiptap/core";
import type { Editor } from "@tiptap/react";

/**
 * Renders the `elementId` node attr (set in documentToTiptap.ts from the
 * backend Element.id) as `data-element-id`, so a DOM node can be mapped back
 * to its source Element. Used by StructurePanel's click-to-scroll and by
 * getSelectedElementId below (PropertiesPanel's selection tracking).
 */
export const ElementId = Extension.create({
  name: "elementId",
  addGlobalAttributes() {
    return [
      {
        types: ["heading", "paragraph", "blockquote", "codeBlock", "bulletList", "orderedList", "taskList", "table", "image", "pageBreak", "horizontalRule", "caption", "footnote"],
        attributes: {
          elementId: {
            default: null,
            // Enter splits a paragraph in two: the new one is a new element and
            // must not inherit this id (two blocks with one id would save as one).
            keepOnSplit: false,
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

/**
 * Walks up from the current selection's deepest node looking for the first
 * ancestor carrying an elementId attr -- e.g. a click inside a table cell's
 * paragraph resolves to the enclosing table's id, since only the table node
 * itself gets one (matches resolvedStyles' existing table-level granularity).
 */
export function getSelectedElementId(editor: Editor): string | null {
  const { $from } = editor.state.selection;
  for (let depth = $from.depth; depth >= 0; depth--) {
    const elementId = $from.node(depth).attrs?.elementId;
    if (elementId) return elementId as string;
  }
  return null;
}
