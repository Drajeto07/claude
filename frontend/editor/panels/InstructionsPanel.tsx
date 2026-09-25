"use client";

import { AlertTriangle, CheckCircle2, Redo2, Undo2 } from "lucide-react";

import { JobProgressBar } from "@/components/JobProgressBar";
import type { FormattingState } from "@/editor/useFormatting";
import type { History } from "@/editor/useHistory";

/**
 * The "Инструкции" rail panel -- free-text formatting instructions, and undo/redo
 * of saved changes. Shares its formatting state with TemplatesPanel (see
 * useFormatting.ts) so this panel's "Apply" always includes whatever template
 * is currently selected, never silently clearing it.
 */
export function InstructionsPanel({ state, history }: { state: FormattingState; history: History }) {
  const { instructionsText, setInstructionsText, setInstructionsFile, isApplying, applyingFrom, progress, notice, handleApply } = state;
  const error = state.error ?? history.error;
  const isHistoryPending = history.pending;
  const handleUndo = history.undo;
  const handleRedo = history.redo;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Instructions</span>
          <textarea
            value={instructionsText}
            onChange={(e) => setInstructionsText(e.target.value)}
            rows={4}
            placeholder="e.g. &quot;make the title bold&quot;, &quot;delete the second paragraph&quot;, &quot;add a page break after the intro&quot;"
            className="rounded-lg border border-zinc-300 bg-white p-2 text-sm text-zinc-900 focus:border-accent focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          />
        </label>
        <input
          type="file"
          accept=".txt,.pdf"
          onChange={(e) => setInstructionsFile(e.target.files?.[0] ?? null)}
          className="text-xs text-zinc-600 dark:text-zinc-400"
        />
        <button
          type="button"
          onClick={() => handleApply("instructions")}
          disabled={isApplying}
          className="rounded-full bg-accent px-6 py-2.5 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isApplying ? "Applying..." : "Apply instructions"}
        </button>
        {applyingFrom === "instructions" && progress && <JobProgressBar progress={progress} />}
        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        {notice && (
          <p
            className={`flex items-start gap-1.5 text-sm ${
              notice.kind === "success" ? "text-green-700 dark:text-green-400" : "text-amber-700 dark:text-amber-400"
            }`}
          >
            {notice.kind === "success" ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            ) : (
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            )}
            {notice.text}
          </p>
        )}
      </div>

      <div className="flex gap-3 border-t border-zinc-200 pt-3 text-xs dark:border-zinc-800">
        <button
          type="button"
          onClick={handleUndo}
          disabled={isHistoryPending}
          className="flex items-center gap-1 text-zinc-500 hover:text-accent disabled:opacity-50 dark:text-zinc-400"
        >
          <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
          Undo formatting
        </button>
        <button
          type="button"
          onClick={handleRedo}
          disabled={isHistoryPending}
          className="flex items-center gap-1 text-zinc-500 hover:text-accent disabled:opacity-50 dark:text-zinc-400"
        >
          <Redo2 className="h-3.5 w-3.5" aria-hidden="true" />
          Redo formatting
        </button>
      </div>

      <p className="text-xs text-zinc-500 dark:text-zinc-400">Every change, and the original, are in the History panel.</p>
    </div>
  );
}
