/** Page sizes the editor, the template preview and both backend exporters
 * (export/docx_export.py, export/pdf_export.py) agree on. */
export const PAGE_DIMENSIONS_MM: Record<string, { width: number; height: number }> = {
  A4: { width: 210, height: 297 },
  Letter: { width: 216, height: 279 },
  Legal: { width: 216, height: 356 },
};

export const PX_PER_MM = 96 / 25.4;

export function pageWidthMm(pageSize: string, orientation: string): number {
  const dimensions = PAGE_DIMENSIONS_MM[pageSize] ?? PAGE_DIMENSIONS_MM.A4;
  return orientation === "landscape" ? dimensions.height : dimensions.width;
}

export function pageHeightMm(pageSize: string, orientation: string): number {
  const dimensions = PAGE_DIMENSIONS_MM[pageSize] ?? PAGE_DIMENSIONS_MM.A4;
  return orientation === "landscape" ? dimensions.width : dimensions.height;
}
