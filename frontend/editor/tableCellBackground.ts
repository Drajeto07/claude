import { Extension } from "@tiptap/core";

/**
 * Cell shading (TableCell.background in the Document Model) as a
 * `backgroundColor` attribute on table cells and header cells.
 */
export const TableCellBackground = Extension.create({
  name: "tableCellBackground",
  addGlobalAttributes() {
    return [
      {
        types: ["tableCell", "tableHeader"],
        attributes: {
          backgroundColor: {
            default: null,
            parseHTML: (element: HTMLElement) => element.style.backgroundColor || null,
            renderHTML: (attributes: Record<string, unknown>) => {
              const color = attributes.backgroundColor as string | null;
              return color ? { style: `background-color: ${color}` } : {};
            },
          },
        },
      },
    ];
  },
});
