import { CloudOff, FilePlus2, Minus, Plus, Scan } from "lucide-react";

import type { SaveStatus } from "@/editor/useAutoSave";

const ZOOM_STEPS = [0.5, 0.75, 0.9, 1, 1.1, 1.25, 1.5];

function SaveState({ status, onRetry }: { status: SaveStatus; onRetry: () => void }) {
  switch (status) {
    case "saving":
      return <span className="text-zinc-400 dark:text-zinc-500">Saving…</span>;
    case "saved":
      return <span className="text-zinc-400 dark:text-zinc-500">Saved</span>;
    case "error":
      return (
        <span className="flex items-center gap-1.5 text-red-600 dark:text-red-400">
          Failed to save
          <button type="button" onClick={onRetry} className="font-medium underline hover:no-underline">
            Retry
          </button>
        </span>
      );
    case "offline":
      return (
        <span className="flex items-center gap-1 text-amber-700 dark:text-amber-400" title="Your changes stay here and are saved once the connection is back.">
          <CloudOff className="h-3.5 w-3.5" aria-hidden="true" />
          Offline – saved when you&apos;re back online
        </span>
      );
    case "conflict":
      return <span className="text-amber-700 dark:text-amber-400">Conflict – changed elsewhere</span>;
    default:
      return null;
  }
}

/**
 * The status bar under the pages (like Word's): add a page, the page count,
 * whether the typing is saved (корекции.docx §29), and zoom.
 */
export function EditorStatusBar({
  zoom,
  onZoomChange,
  onFitWidth,
  pageCount,
  onAddPage,
  saveStatus,
  onRetrySave,
}: {
  zoom: number;
  onZoomChange: (zoom: number) => void;
  onFitWidth: () => void;
  pageCount: number;
  onAddPage: () => void;
  saveStatus: SaveStatus;
  onRetrySave: () => void;
}) {
  const index = ZOOM_STEPS.findIndex((step) => step >= zoom);

  function step(delta: number) {
    const nextIndex = Math.min(ZOOM_STEPS.length - 1, Math.max(0, (index === -1 ? ZOOM_STEPS.length - 1 : index) + delta));
    onZoomChange(ZOOM_STEPS[nextIndex]);
  }

  return (
    <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-t border-zinc-200 bg-white px-4 text-xs text-zinc-500 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-400">
      <div className="flex min-w-0 items-center gap-3">
        <button
          type="button"
          onClick={onAddPage}
          className="flex shrink-0 items-center gap-1 rounded px-2 py-1 text-zinc-600 hover:bg-zinc-100 hover:text-accent dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          <FilePlus2 className="h-3.5 w-3.5" aria-hidden="true" />
          New page
        </button>
        <span className="h-4 w-px shrink-0 bg-zinc-200 dark:bg-zinc-700" aria-hidden="true" />
        <span className="shrink-0">
          {pageCount} {pageCount === 1 ? "page" : "pages"}
        </span>
        <span role="status" className="min-w-0 truncate">
          <SaveState status={saveStatus} onRetry={onRetrySave} />
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <button
          type="button"
          aria-label="Zoom out"
          title="Zoom out"
          onClick={() => step(-1)}
          className="flex h-7 w-7 items-center justify-center rounded text-zinc-500 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
        >
          <Minus className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
        <span className="w-10 text-center tabular-nums">{Math.round(zoom * 100)}%</span>
        <button
          type="button"
          aria-label="Zoom in"
          title="Zoom in"
          onClick={() => step(1)}
          className="flex h-7 w-7 items-center justify-center rounded text-zinc-500 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
        <span className="mx-1 h-5 w-px bg-zinc-200 dark:bg-zinc-700" aria-hidden="true" />
        <button
          type="button"
          aria-label="Fit width"
          title="Fit width"
          onClick={onFitWidth}
          className="flex h-7 items-center gap-1 rounded px-2 text-zinc-500 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
        >
          <Scan className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="hidden sm:inline">Fit width</span>
        </button>
      </div>
    </div>
  );
}
