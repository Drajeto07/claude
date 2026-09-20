"use client";

import { EditorContent, useEditor } from "@tiptap/react";
import { useEffect, useRef, useState, type CSSProperties } from "react";

import { FormattingPanel } from "@/components/FormattingPanel";
import { OutlinePanel } from "@/components/OutlinePanel";
import { Toolbar } from "@/components/Toolbar";
import { documentToTiptapJSON } from "@/editor/documentToTiptap";
import { editorExtensions } from "@/editor/extensions";
import type { Document } from "@/types/document";

const PAGE_DIMENSIONS_MM: Record<string, { width: number; height: number }> = {
  A4: { width: 210, height: 297 },
  Letter: { width: 216, height: 279 },
  Legal: { width: 216, height: 356 },
};

const PX_PER_MM = 96 / 25.4;
const SEAM_BAND_PX = 14;

// Continuous-scroll single-page visual approximation only -- real multi-page
// reflow, where content actually moves between fixed-height pages as you
// type, is a separate, much bigger engineering effort (no Tiptap/ProseMirror
// library does this for free). This phase only *looks* paginated.
function pageWidthMm(pageSize: string, orientation: string): number {
  const dimensions = PAGE_DIMENSIONS_MM[pageSize] ?? PAGE_DIMENSIONS_MM.A4;
  return orientation === "landscape" ? dimensions.height : dimensions.width;
}

function pageHeightPx(pageSize: string, orientation: string): number {
  const dimensions = PAGE_DIMENSIONS_MM[pageSize] ?? PAGE_DIMENSIONS_MM.A4;
  const heightMm = orientation === "landscape" ? dimensions.width : dimensions.height;
  return heightMm * PX_PER_MM;
}

// A shadow band sits at the START of each repeat unit, and the repeat unit's
// length is exactly `heightPx` (the position of the last color-stop) -- that
// combination is what makes seams land on exact multiples of the page height
// with no cumulative drift. backgroundPosition then shifts the whole pattern
// down by one unit, so the first seam appears *after* page 1 instead of
// right at the top edge.
function pageSeamStyle(heightPx: number): CSSProperties {
  return {
    backgroundImage: `repeating-linear-gradient(to bottom, rgba(128,128,128,0.35) 0px, rgba(128,128,128,0.12) 6px, transparent ${SEAM_BAND_PX}px, transparent ${heightPx}px)`,
    backgroundPosition: `0 ${heightPx}px`,
  };
}

export function DocumentEditor({ initialDocument }: { initialDocument: Document }) {
  const [doc, setDoc] = useState(initialDocument);
  const [pageCount, setPageCount] = useState(1);
  const paperRef = useRef<HTMLDivElement>(null);
  const editor = useEditor({
    extensions: editorExtensions,
    content: documentToTiptapJSON(doc),
    immediatelyRender: false,
  });

  const { settings } = doc;
  const heightPx = pageHeightPx(settings.pageSize, settings.orientation);

  // Estimates page count from rendered content height vs. the configured
  // page height -- an estimate, not a real page count, since content never
  // actually reflows into separate pages this phase.
  useEffect(() => {
    const node = paperRef.current;
    if (!node) return;
    const observer = new ResizeObserver(() => {
      setPageCount(Math.max(1, Math.ceil(node.scrollHeight / heightPx)));
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [heightPx]);

  function handleFormatted(updated: Document) {
    setDoc(updated);
    editor?.commands.setContent(documentToTiptapJSON(updated));
  }

  const pageWidth = `${pageWidthMm(settings.pageSize, settings.orientation)}mm`;
  const paperPadding: CSSProperties = {
    paddingTop: `${settings.marginTopCm}cm`,
    paddingBottom: `${settings.marginBottomCm}cm`,
    paddingLeft: `${settings.marginLeftCm}cm`,
    paddingRight: `${settings.marginRightCm}cm`,
  };

  return (
    <div className="px-6 py-10">
      <div className="mx-auto max-w-3xl">
        <p className="mb-6 text-sm text-zinc-500">
          Editable draft &mdash; edits stay in your browser only; there is no save yet in this phase.
        </p>
        <FormattingPanel document={doc} onFormatted={handleFormatted} />
      </div>

      <div className="flex justify-center gap-6">
        <aside className="hidden w-56 shrink-0 lg:block">
          <OutlinePanel elements={doc.elements} />
        </aside>

        <div className="w-full" style={{ maxWidth: pageWidth }}>
          <Toolbar editor={editor} />
          {settings.header && (
            <p className="mb-2 border-b border-zinc-200 pb-2 text-center text-xs text-zinc-500 dark:border-zinc-800">
              {settings.header}
            </p>
          )}
          <div
            ref={paperRef}
            className="rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
            style={{ ...paperPadding, ...pageSeamStyle(heightPx) }}
          >
            <EditorContent editor={editor} />
          </div>
          {(settings.footer || settings.showPageNumbers) && (
            <p className="mt-2 border-t border-zinc-200 pt-2 text-center text-xs text-zinc-500 dark:border-zinc-800">
              {[settings.footer, settings.showPageNumbers ? `Page 1 of ${pageCount}` : null].filter(Boolean).join(" · ")}
            </p>
          )}
        </div>
      </div>

      <p className="mx-auto mt-3 max-w-3xl text-center text-xs text-zinc-400">
        Page breaks shown here are a visual estimate from content height, not real pagination -- content still flows continuously.
      </p>
    </div>
  );
}
