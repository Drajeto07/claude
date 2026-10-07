import { Extension } from "@tiptap/core";

import type { ListNumbering } from "@/types/document";

/**
 * A list's own numbering from a Word file (tracker DOCX-016): each level's format,
 * label, start and indent, and a top-level format the HTML list types can't say
 * (01, а б в). The editor keeps it on the list -- not shown yet -- so a save gives it
 * back as it was (tiptapToDocument.ts numberingOf); a list made or nested here has none.
 */
export type ListNumberingAttr = Pick<ListNumbering, "format" | "levels"> & { language?: string | null };

export const ListNumberingAttribute = Extension.create({
  name: "listNumbering",
  addGlobalAttributes() {
    return [
      {
        types: ["orderedList", "bulletList"],
        attributes: {
          numbering: { default: null, rendered: false },
        },
      },
    ];
  },
});
