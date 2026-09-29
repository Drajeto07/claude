"use client";

import { EditorContent, type Editor } from "@tiptap/react";
import type { CSSProperties, RefObject } from "react";

import type { PageChrome } from "@/editor/sectionHeaders";
import { CM_TO_PX, PAGE_GAP_PX, type PageSettings } from "@/editor/usePageSettings";
import type { DocumentSettings } from "@/types/document";

/** Header/footer text with its page-number fields filled in. */
function fillPageFields(text: string, page: string, pages: number): string {
  return text.replaceAll("{PAGE}", page).replaceAll("{NUMPAGES}", String(pages));
}

/**
 * The pages, as in Word's page view: a grey desk with one sheet per page -- its
 * header, footer and page number drawn in the margins -- and the editor laid
 * over them. The editor's padding is the page margins (see .paged-editor in
 * globals.css), so its first line starts where page 1's text area does; the
 * pagination (editor/pagination.ts) reads the geometry from the data-* attributes.
 */
export function EditorCanvas({
  editor,
  settings,
  page,
  canvasRef,
  showHidden = false,
  chrome = [],
  lastSectionStart = null,
}: {
  editor: Editor | null;
  settings: DocumentSettings;
  page: PageSettings;
  /** The scrolling desk, whose width the fit-to-column zoom follows (usePageSettings). */
  canvasRef: RefObject<HTMLDivElement | null>;
  /** Show Word's hidden text (editor/hiddenText.ts), which is otherwise hidden. */
  showHidden?: boolean;
  /** Each page's header, footer and page number, from its section (editor/sectionHeaders.ts). */
  chrome?: PageChrome[];
  /** Where the last section's page numbers restart, for pagination's even and odd starts (Document.lastSection). */
  lastSectionStart?: number | null;
}) {
  const { pageCount, heightPx, stridePx, zoom } = page;
  const pagedStyle = {
    height: pageCount * stridePx - PAGE_GAP_PX,
    "--page-margin-top": `${settings.marginTopCm}cm`,
    "--page-margin-right": `${settings.marginRightCm}cm`,
    "--page-margin-bottom": `${settings.marginBottomCm}cm`,
    "--page-margin-left": `${settings.marginLeftCm}cm`,
  } as CSSProperties;
  const margins = { paddingLeft: `${settings.marginLeftCm}cm`, paddingRight: `${settings.marginRightCm}cm` };

  return (
    <div ref={canvasRef} className="flex-1 overflow-y-auto bg-[#e7e8eb] px-4 py-8 dark:bg-black sm:px-6">
      <p className="mx-auto mb-6 max-w-3xl text-center text-xs text-zinc-500">
        Edits save automatically a moment after you stop typing. Pages are laid out as they print: what doesn&apos;t fit on a page
        continues on the next one.
      </p>

      <div className="mx-auto" style={{ width: `${settings.pageWidthMm}mm`, zoom }}>
        <div
          className={`paged-editor relative${showHidden ? " show-hidden" : ""}`}
          style={pagedStyle}
          data-page-height={heightPx}
          data-page-gap={PAGE_GAP_PX}
          data-margin-top={settings.marginTopCm * CM_TO_PX}
          data-margin-bottom={settings.marginBottomCm * CM_TO_PX}
          data-scale={zoom}
          data-last-section-start={lastSectionStart ?? undefined}
        >
          {Array.from({ length: pageCount }, (_, index) => {
            const own = chrome[index] ?? { header: settings.header ?? null, footer: settings.footer ?? null, label: String(index + 1) };
            const header = own.header ? fillPageFields(own.header, own.label, pageCount) : null;
            const footer = [own.footer ? fillPageFields(own.footer, own.label, pageCount) : null, settings.showPageNumbers ? `Page ${own.label}` : null]
              .filter(Boolean)
              .join(" · ");
            return (
              <div
                key={index}
                data-page={index + 1}
                aria-hidden="true"
                className="pointer-events-none absolute inset-x-0 border border-zinc-300 bg-white shadow-[0_1px_3px_rgba(0,0,0,0.12),0_4px_14px_rgba(0,0,0,0.08)] dark:border-zinc-700 dark:bg-zinc-900"
                style={{ top: index * stridePx, height: heightPx }}
              >
                {header && (
                  <div data-part="header" className="absolute inset-x-0 -translate-y-1/2 truncate text-center text-[11px] text-zinc-500" style={{ top: `${settings.marginTopCm / 2}cm`, ...margins }}>
                    {header}
                  </div>
                )}
                {footer && (
                  <div data-part="footer" className="absolute inset-x-0 translate-y-1/2 truncate text-center text-[11px] text-zinc-500" style={{ bottom: `${settings.marginBottomCm / 2}cm`, ...margins }}>
                    {footer}
                  </div>
                )}
              </div>
            );
          })}
          <div className="relative z-10 h-full">
            <EditorContent editor={editor} className="h-full" />
          </div>
        </div>
      </div>
    </div>
  );
}
