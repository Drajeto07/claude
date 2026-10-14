"use client";

import { AlertTriangle, CheckCircle2, Redo2, Undo2 } from "lucide-react";

import { JobProgressBar } from "@/components/JobProgressBar";
import { ProposalsList } from "@/editor/panels/ProposalsList";
import type { FormattingState } from "@/editor/useFormatting";
import type { History } from "@/editor/useHistory";
import { useI18n } from "@/i18n/I18nProvider";

/**
 * The Instructions rail panel -- free-text formatting instructions, and (classic
 * editor only: `showHistory`) undo/redo of saved changes; E2 has one Undo/Redo in its top bar. Shares its formatting state with TemplatesPanel (see
 * useFormatting.ts) so this panel's "Apply" always includes whatever template
 * is currently selected, never silently clearing it.
 */
export function InstructionsPanel({ state, history, showHistory = true }: { state: FormattingState; history: History; showHistory?: boolean }) {
  const { m } = useI18n();
  const t = m.edPanels.instructions;
  const { instructionsText, setInstructionsText, setInstructionsFile, isApplying, applyingFrom, progress, notice, handleApply } = state;
  const error = state.error ?? history.error;
  const isHistoryPending = history.pending;
  const handleUndo = history.undo;
  const handleRedo = history.redo;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted">{t.label}</span>
          <textarea
            value={instructionsText}
            onChange={(e) => setInstructionsText(e.target.value)}
            rows={4}
            placeholder={t.placeholder}
            className="rounded-lg border border-line-strong bg-surface p-2 text-sm text-foreground focus:border-accent focus:outline-none"
          />
        </label>
        <input
          type="file"
          accept=".txt,.pdf"
          onChange={(e) => setInstructionsFile(e.target.files?.[0] ?? null)}
          className="text-xs text-muted"
        />
        <button
          type="button"
          onClick={() => handleApply("instructions")}
          disabled={isApplying}
          className="rounded-full bg-accent px-6 py-2.5 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isApplying ? m.edPanels.common.applying : t.apply}
        </button>
        {applyingFrom === "instructions" && progress && <JobProgressBar progress={progress} />}
        {error && <p className="text-sm text-danger">{error}</p>}
        {notice && (
          <p
            className={`flex items-start gap-1.5 text-sm ${
              notice.kind === "success" ? "text-success" : "text-warning"
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

      <ProposalsList source="instruction" />

      {showHistory && (
      <div className="flex gap-3 border-t border-line pt-3 text-xs">
        <button
          type="button"
          onClick={handleUndo}
          disabled={isHistoryPending}
          className="flex items-center gap-1 text-muted hover:text-accent disabled:opacity-50"
        >
          <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
          {t.undo}
        </button>
        <button
          type="button"
          onClick={handleRedo}
          disabled={isHistoryPending}
          className="flex items-center gap-1 text-muted hover:text-accent disabled:opacity-50"
        >
          <Redo2 className="h-3.5 w-3.5" aria-hidden="true" />
          {t.redo}
        </button>
      </div>
      )}

      <p className="text-xs text-muted">{t.historyNote}</p>
    </div>
  );
}
