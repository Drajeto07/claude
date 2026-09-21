"use client";

import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import { ListTree, SlidersHorizontal } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties } from "react";

import { AppHeader } from "@/components/AppHeader";
import { EditorContextBar } from "@/components/EditorContextBar";
import { ExportPanel } from "@/components/ExportPanel";
import { FormattingPanel } from "@/components/FormattingPanel";
import { OutlinePanel } from "@/components/OutlinePanel";
import { SidePanel, type SidePanelTab } from "@/components/SidePanel";
import { ViewControls } from "@/components/ViewControls";
import { documentToTiptapJSON } from "@/editor/documentToTiptap";
import { getSelectedElementId } from "@/editor/elementId";
import { editorExtensions } from "@/editor/extensions";
import { useEditorForceUpdate } from "@/editor/useEditorForceUpdate";
import type { Document } from "@/types/document";

// After setContent() replaces the whole document, ProseMirror's selection
// resets -- without this, editing one property in PropertiesPanel would
// deselect the element being edited, forcing a re-click after every change.
function selectElementById(editor: Editor, elementId: string) {
  let targetPos: number | null = null;
  editor.state.doc.descendants((node, pos) => {
    if (targetPos !== null) return false;
    if (node.attrs?.elementId === elementId) {
      targetPos = pos;
      return false;
    }
    return true;
  });
  if (targetPos !== null) editor.commands.setTextSelection(targetPos + 1);
}

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

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 2;
const CANVAS_SIDE_PADDING_PX = 48; // matches the scroll container's px-4/sm:px-6

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
  const [zoom, setZoom] = useState(1);
  const paperRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const editor = useEditor({
    extensions: editorExtensions,
    content: documentToTiptapJSON(doc),
    immediatelyRender: false,
  });
  useEditorForceUpdate(editor);
  const selectedElementId = editor ? getSelectedElementId(editor) : null;

  const { settings } = doc;
  const heightPx = pageHeightPx(settings.pageSize, settings.orientation);

  // Estimates page count from rendered content height vs. the configured
  // page height -- an estimate, not a real page count, since content never
  // actually reflows into separate pages this phase. `zoom` (a real,
  // layout-affecting CSS property, unlike transform) scales the measured
  // scrollHeight along with the content, so it's divided back out here to
  // keep the estimate zoom-independent.
  useEffect(() => {
    const node = paperRef.current;
    if (!node) return;
    const observer = new ResizeObserver(() => {
      setPageCount(Math.max(1, Math.ceil(node.scrollHeight / zoom / heightPx)));
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [heightPx, zoom]);

  function handleFitWidth() {
    const container = canvasRef.current;
    if (!container) return;
    const pageWidthPx = pageWidthMm(settings.pageSize, settings.orientation) * PX_PER_MM;
    const available = container.clientWidth - CANVAS_SIDE_PADDING_PX;
    setZoom(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, available / pageWidthPx)));
  }

  function applyDocumentUpdate(updated: Document) {
    const previousSelection = editor ? getSelectedElementId(editor) : null;
    setDoc(updated);
    editor?.commands.setContent(documentToTiptapJSON(updated));
    if (editor && previousSelection) selectElementById(editor, previousSelection);
  }

  const pageWidth = `${pageWidthMm(settings.pageSize, settings.orientation)}mm`;
  const paperPadding: CSSProperties = {
    paddingTop: `${settings.marginTopCm}cm`,
    paddingBottom: `${settings.marginBottomCm}cm`,
    paddingLeft: `${settings.marginLeftCm}cm`,
    paddingRight: `${settings.marginRightCm}cm`,
  };

  const sidePanelTabs: SidePanelTab[] = [
    {
      id: "format",
      label: "Format",
      icon: <SlidersHorizontal className="h-[18px] w-[18px]" aria-hidden="true" />,
      content: <FormattingPanel document={doc} onFormatted={applyDocumentUpdate} />,
    },
    {
      id: "outline",
      label: "Outline",
      icon: <ListTree className="h-[18px] w-[18px]" aria-hidden="true" />,
      content: <OutlinePanel elements={doc.elements} />,
    },
  ];

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <AppHeader
        rightSlot={
          <>
            <span className="hidden max-w-[240px] truncate text-sm font-medium text-zinc-600 dark:text-zinc-300 sm:inline">
              {doc.metadata.title}
            </span>
            <ExportPanel documentId={doc.id} />
          </>
        }
      />
      <div className="flex min-h-0 flex-1">
        <SidePanel tabs={sidePanelTabs} defaultTabId="format" />

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="border-b border-zinc-200 px-4 pt-3 pb-0 dark:border-zinc-800 sm:px-6">
            <EditorContextBar
              editor={editor}
              document={doc}
              selectedElementId={selectedElementId}
              onUpdated={applyDocumentUpdate}
            />
          </div>

          <div ref={canvasRef} className="flex-1 overflow-y-auto px-4 py-8 sm:px-6">
            <p className="mx-auto mb-6 max-w-3xl text-center text-xs text-zinc-400">
              Editable draft &mdash; edits stay in your browser only; there is no save yet in this phase. Exports
              reflect the last applied template/formatting, not unsaved text edits made directly in the editor below.
            </p>

            <div className="mx-auto" style={{ width: pageWidth, zoom }}>
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
              {settings.footer && (
                <p className="mt-2 border-t border-zinc-200 pt-2 text-center text-xs text-zinc-500 dark:border-zinc-800">
                  {settings.footer}
                </p>
              )}
            </div>
          </div>

          <ViewControls zoom={zoom} onZoomChange={setZoom} onFitWidth={handleFitWidth} pageCount={pageCount} />
        </div>
      </div>
    </div>
  );
}
