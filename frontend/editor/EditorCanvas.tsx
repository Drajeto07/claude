"use client";

import { EditorContent, type Editor } from "@tiptap/react";
import type { CSSProperties, RefObject } from "react";

import type { PageChrome } from "@/editor/sectionHeaders";
import { PAGE_GAP_PX, type PageSettings } from "@/editor/usePageSettings";
import type { DocumentSettings } from "@/types/document";

/** Header/footer text with its page-number fields filled in. */
function fillPageFields(text: string, page: string, pages: number): string {
  return text.replaceAll("{PAGE}", page).replaceAll("{NUMPAGES}", String(pages));
}

/**
 * The pages, as in Word's page view: a grey desk with one sheet per page -- its
 * header and footer at their distances from its edges, its page number -- and the
 * editor laid over them. Each page has its section's size and margins (DOCX-015),
 * centred on the desk, which is as wide as the widest. The editor's padding is the
 * document's own page's margins (see .paged-editor in globals.css), so its first
 * line starts where page 1's text area does; the pagination (editor/pagination.ts)
 * reads that page from the data-* attributes and says where every page is.
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
  const { pages, pageCount, base, widest, heightPx, zoom } = page;
  const aside = (widest - base.width) / 2; // the document's page, centred on the desk
  const pagedStyle = {
    height: heightPx,
    "--page-margin-top": `${pages[0].box.marginTop}px`,
    "--page-margin-right": `${aside + base.marginRight}px`,
    "--page-margin-bottom": `${base.marginBottom}px`,
    "--page-margin-left": `${aside + base.marginLeft}px`,
  } as CSSProperties;

  return (
    <div ref={canvasRef} className="flex-1 overflow-y-auto bg-[#e7e8eb] px-4 py-8 dark:bg-black sm:px-6">
      <p className="mx-auto mb-6 max-w-3xl text-center text-xs text-zinc-500">
        Edits save automatically a moment after you stop typing. Pages are laid out as they print: what doesn&apos;t fit on a page
        continues on the next one.
      </p>

      <div className="mx-auto" style={{ width: widest, zoom }}>
        <div
          className={`paged-editor relative${showHidden ? " show-hidden" : ""}`}
          style={pagedStyle}
          data-page-width={base.width}
          data-page-height={base.height}
          data-page-gap={PAGE_GAP_PX}
          data-margin-top={base.marginTop}
          data-margin-bottom={base.marginBottom}
          data-margin-left={base.marginLeft}
          data-margin-right={base.marginRight}
          data-header-distance={base.headerDistance}
          data-footer-distance={base.footerDistance}
          data-scale={zoom}
          data-last-section-start={lastSectionStart ?? undefined}
        >
          {pages.map(({ top, box }, index) => {
            const own = chrome[index] ?? { header: settings.header ?? null, footer: settings.footer ?? null, label: String(index + 1) };
            const header = own.header ? fillPageFields(own.header, own.label, pageCount) : null;
            const footer = [own.footer ? fillPageFields(own.footer, own.label, pageCount) : null, settings.showPageNumbers ? `Page ${own.label}` : null]
              .filter(Boolean)
              .join(" · ");
            const sides = { paddingLeft: box.marginLeft, paddingRight: box.marginRight };
            return (
              <div
                key={index}
                data-page={index + 1}
                aria-hidden="true"
                className="pointer-events-none absolute border border-zinc-300 bg-white shadow-[0_1px_3px_rgba(0,0,0,0.12),0_4px_14px_rgba(0,0,0,0.08)] dark:border-zinc-700 dark:bg-zinc-900"
                style={{ top, height: box.height, width: box.width, left: (widest - box.width) / 2 }}
              >
                {header && (
                  <div data-part="header" className="absolute inset-x-0 truncate text-center text-[11px] leading-none text-zinc-500" style={{ top: box.headerDistance, ...sides }}>
                    {header}
                  </div>
                )}
                {footer && (
                  <div data-part="footer" className="absolute inset-x-0 truncate text-center text-[11px] leading-none text-zinc-500" style={{ bottom: box.footerDistance, ...sides }}>
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
