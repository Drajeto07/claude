import { Node, mergeAttributes } from "@tiptap/core";

import type { Element } from "@/types/document";

/**
 * A Word section break -- ElementType.SECTION_BREAK (tracker DOCX-015). Like a page
 * break it is an atomic, selectable block that can be moved or deleted; it carries
 * the section's settings (`section`: Element.sectionBreak) unchanged, and shows how
 * the next section starts and what the pages above it are set to. Pagination starts
 * a new page after it unless the next section is continuous, on an even or odd page
 * where it says so (editor/pagination.ts).
 */

export type SectionSettings = NonNullable<Element["sectionBreak"]>;

const STARTS: Record<SectionSettings["start"], string> = {
  nextPage: "next page",
  continuous: "continuous",
  evenPage: "even page",
  oddPage: "odd page",
};

/** "Section break (next page)". */
export function sectionBreakLabel(settings: SectionSettings | null | undefined): string {
  return `Section break (${STARTS[settings?.start ?? "nextPage"] ?? "next page"})`;
}

/** What the pages above the break are set to, where it isn't the document's own: "landscape · 27.9 × 21.6 cm · 2 columns". */
export function sectionSummary(settings: SectionSettings | null | undefined): string {
  if (!settings) return "";
  const parts: string[] = [];
  if (settings.orientation) parts.push(settings.orientation);
  if (settings.pageWidthMm && settings.pageHeightMm) {
    parts.push(`${(settings.pageWidthMm / 10).toFixed(1)} × ${(settings.pageHeightMm / 10).toFixed(1)} cm`);
  }
  if (settings.columns && settings.columns > 1) parts.push(`${settings.columns} columns`);
  if (settings.pageNumberStart !== null && settings.pageNumberStart !== undefined) parts.push(`pages from ${settings.pageNumberStart}`);
  return parts.join(" · ");
}

function parseSection(value: string | null): SectionSettings | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value) as SectionSettings;
    return parsed && typeof parsed === "object" && typeof parsed.start === "string" ? parsed : null;
  } catch {
    return null;
  }
}

export const SectionBreak = Node.create({
  name: "sectionBreak",
  group: "block",
  atom: true,
  selectable: true,
  draggable: false,

  addAttributes() {
    return {
      section: {
        default: null,
        parseHTML: (element: HTMLElement) => parseSection(element.getAttribute("data-section")),
        renderHTML: (attributes: Record<string, unknown>) => (attributes.section ? { "data-section": JSON.stringify(attributes.section) } : {}),
      },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-section-break="true"]' }];
  },

  renderHTML({ HTMLAttributes, node }) {
    const settings = node.attrs.section as SectionSettings | null;
    const summary = sectionSummary(settings);
    return [
      "div",
      mergeAttributes(HTMLAttributes, { "data-section-break": "true", "data-start": settings?.start ?? "nextPage", contenteditable: "false" }),
      ["div", { class: "section-break-label" }, sectionBreakLabel(settings)],
      ...(summary ? [["div", { class: "section-break-summary" }, `Above: ${summary}`]] : []),
    ];
  },
});
