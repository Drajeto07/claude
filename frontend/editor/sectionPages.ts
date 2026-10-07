import { PX_PER_MM } from "@/editor/pageGeometry";
import type { SectionSettings } from "@/editor/sectionHeaders";
import type { DocumentSettings } from "@/types/document";

/**
 * Each section's page in the editor, as Word and the PDF have it (tracker DOCX-015):
 * its own size -- or the document's, turned to its orientation -- its own margins
 * and header and footer distances over the document's. The same rules as the PDF's
 * (backend export/pdf_export.py _SectionPage.of). editor/pagination.ts lays each
 * page out at its section's page; EditorCanvas draws it.
 */

const CM_TO_PX = 10 * PX_PER_MM;
/** Word's default header and footer distance. */
export const HEADER_DISTANCE_CM = 1.27;

/** A page's size, margins and header and footer distances, in CSS px at 100%. */
export type PageBox = {
  width: number;
  height: number;
  marginTop: number;
  marginBottom: number;
  marginLeft: number;
  marginRight: number;
  headerDistance: number;
  footerDistance: number;
};

/** A page as pagination lays it out: where it starts on the sheet (px), its section, its box. */
export type PageSlot = { top: number; section: number; box: PageBox };

type SectionPageSettings = Pick<
  SectionSettings,
  | "orientation"
  | "pageWidthMm"
  | "pageHeightMm"
  | "marginTopCm"
  | "marginBottomCm"
  | "marginLeftCm"
  | "marginRightCm"
  | "headerDistanceCm"
  | "footerDistanceCm"
>;

/** The document's own page: the last section's (DocumentSettings, and Document.lastSection's distances,
 * and its paper size when the app lists none like it: DOCX-015A). */
export function basePage(
  settings: Pick<DocumentSettings, "pageWidthMm" | "pageHeightMm" | "marginTopCm" | "marginBottomCm" | "marginLeftCm" | "marginRightCm">,
  last?: Partial<Pick<SectionSettings, "headerDistanceCm" | "footerDistanceCm" | "pageWidthMm" | "pageHeightMm">> | null,
): PageBox {
  const custom = last?.pageWidthMm && last.pageHeightMm ? { width: last.pageWidthMm, height: last.pageHeightMm } : null;
  return {
    width: (custom?.width ?? settings.pageWidthMm) * PX_PER_MM,
    height: (custom?.height ?? settings.pageHeightMm) * PX_PER_MM,
    marginTop: settings.marginTopCm * CM_TO_PX,
    marginBottom: settings.marginBottomCm * CM_TO_PX,
    marginLeft: settings.marginLeftCm * CM_TO_PX,
    marginRight: settings.marginRightCm * CM_TO_PX,
    headerDistance: (last?.headerDistanceCm ?? HEADER_DISTANCE_CM) * CM_TO_PX,
    footerDistance: (last?.footerDistanceCm ?? HEADER_DISTANCE_CM) * CM_TO_PX,
  };
}

/** A section's page: its own settings over the document's page (`base`). */
export function sectionPage(section: Partial<SectionPageSettings> | null | undefined, base: PageBox): PageBox {
  let { width, height } = base;
  if (section?.pageWidthMm && section.pageHeightMm) {
    width = section.pageWidthMm * PX_PER_MM;
    height = section.pageHeightMm * PX_PER_MM;
  } else if (section?.orientation && (section.orientation === "landscape") !== width > height) {
    [width, height] = [height, width];
  }
  const own = (value: number | null | undefined, fallback: number) => (value != null ? value * CM_TO_PX : fallback);
  return {
    width,
    height,
    marginTop: own(section?.marginTopCm, base.marginTop),
    marginBottom: own(section?.marginBottomCm, base.marginBottom),
    marginLeft: own(section?.marginLeftCm, base.marginLeft),
    marginRight: own(section?.marginRightCm, base.marginRight),
    headerDistance: own(section?.headerDistanceCm, base.headerDistance),
    footerDistance: own(section?.footerDistanceCm, base.footerDistance),
  };
}

/** How far a section's text column lies from the document's, on each side (px; negative
 * is wider): its page is centred where the document's is. */
export function columnShift(box: PageBox, base: PageBox): { left: number; right: number } {
  const edge = (base.width - box.width) / 2;
  return { left: edge + box.marginLeft - base.marginLeft, right: edge + box.marginRight - base.marginRight };
}

/** A block's margin on one side moved by `shift` px, over its own inline one ("auto" stays). */
export function shiftedMargin(style: string | null | undefined, side: "left" | "right", shift: number): string {
  const own = style ? new RegExp(`(?:^|;)\\s*margin-${side}\\s*:\\s*([^;]+)`, "i").exec(style)?.[1].trim() : undefined;
  if (own === "auto") return "auto";
  return `calc(${own ?? "0px"} + ${Math.round(shift * 10) / 10}px)`;
}
