import { Minus, Plus, Scan } from "lucide-react";

const ZOOM_STEPS = [0.5, 0.75, 0.9, 1, 1.1, 1.25, 1.5];

/**
 * Word-status-bar-inspired (per Boril's "use Canva and Word as reference"):
 * always-visible zoom + page count, independent of the document's own
 * footer/page-number *content* preview (which stays in the paper itself,
 * gated on settings.footer/showPageNumbers -- that's previewing what's
 * actually exported, not a UI affordance).
 */
export function ViewControls({
  zoom,
  onZoomChange,
  onFitWidth,
  pageCount,
}: {
  zoom: number;
  onZoomChange: (zoom: number) => void;
  onFitWidth: () => void;
  pageCount: number;
}) {
  const index = ZOOM_STEPS.findIndex((step) => step >= zoom);

  function step(delta: number) {
    const nextIndex = Math.min(ZOOM_STEPS.length - 1, Math.max(0, (index === -1 ? ZOOM_STEPS.length - 1 : index) + delta));
    onZoomChange(ZOOM_STEPS[nextIndex]);
  }

  return (
    <div className="flex h-10 shrink-0 items-center justify-between border-t border-zinc-200 bg-white px-4 text-xs text-zinc-500 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-400">
      <span>
        Page 1 of {pageCount} <span className="text-zinc-300 dark:text-zinc-700">&middot;</span> estimate, not real
        pagination
      </span>
      <div className="flex items-center gap-1">
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
          Fit width
        </button>
      </div>
    </div>
  );
}
