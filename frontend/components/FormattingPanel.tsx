"use client";

import { useEffect, useState } from "react";

import { ConflictModal } from "@/components/ConflictModal";
import { formatDocument, listTemplates, redoFormatting, undoFormatting } from "@/services/api";
import type { ConflictResolution, Document, FormattingConflict, TemplateSummary } from "@/types/document";

export function FormattingPanel({
  document,
  onFormatted,
}: {
  document: Document;
  onFormatted: (updated: Document) => void;
}) {
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [templateId, setTemplateId] = useState(document.templateId ?? "");
  const [instructionsText, setInstructionsText] = useState("");
  const [instructionsFile, setInstructionsFile] = useState<File | null>(null);
  const [isApplying, setIsApplying] = useState(false);
  const [isHistoryPending, setIsHistoryPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<FormattingConflict[] | null>(null);

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch(() => setError("Could not load templates. Is the backend running on port 8000?"));
  }, []);

  async function handleApply(resolutions?: ConflictResolution[]) {
    setError(null);
    setIsApplying(true);
    try {
      const result = await formatDocument(document.id, {
        templateId: templateId || undefined,
        instructionsText: instructionsText.trim() || undefined,
        instructionsFile: instructionsFile ?? undefined,
        resolutions,
      });
      if (result.status === "conflicts") {
        setConflicts(result.conflicts);
        return;
      }
      setConflicts(null);
      onFormatted(result.document);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not apply formatting.");
    } finally {
      setIsApplying(false);
    }
  }

  async function handleUndo() {
    setError(null);
    setIsHistoryPending(true);
    try {
      onFormatted(await undoFormatting(document.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nothing to undo.");
    } finally {
      setIsHistoryPending(false);
    }
  }

  async function handleRedo() {
    setError(null);
    setIsHistoryPending(true);
    try {
      onFormatted(await redoFormatting(document.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nothing to redo.");
    } finally {
      setIsHistoryPending(false);
    }
  }

  return (
    <div className="mb-6 rounded-lg border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900/50">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">Formatting</h2>
        <div className="flex gap-2 text-xs">
          <button
            type="button"
            onClick={handleUndo}
            disabled={isHistoryPending}
            className="text-zinc-500 hover:text-zinc-800 disabled:opacity-50 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            &#8630; Undo formatting
          </button>
          <button
            type="button"
            onClick={handleRedo}
            disabled={isHistoryPending}
            className="text-zinc-500 hover:text-zinc-800 disabled:opacity-50 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            &#8631; Redo formatting
          </button>
        </div>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row">
        <select
          value={templateId}
          onChange={(e) => setTemplateId(e.target.value)}
          className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        >
          <option value="">No template</option>
          {templates.map((template) => (
            <option key={template.id} value={template.id}>
              {template.name}
            </option>
          ))}
        </select>
        <textarea
          value={instructionsText}
          onChange={(e) => setInstructionsText(e.target.value)}
          rows={2}
          placeholder="Optional instructions, e.g. &quot;make headings red and Arial&quot;"
          className="flex-1 rounded-lg border border-zinc-300 bg-white p-2 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <input
          type="file"
          accept=".txt,.pdf"
          onChange={(e) => setInstructionsFile(e.target.files?.[0] ?? null)}
          className="text-sm text-zinc-600 dark:text-zinc-400"
        />
        <button
          type="button"
          onClick={() => handleApply()}
          disabled={isApplying}
          className="rounded-full bg-zinc-900 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          {isApplying ? "Applying..." : "Apply formatting"}
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
      {conflicts && (
        <ConflictModal conflicts={conflicts} onCancel={() => setConflicts(null)} onResolve={(resolutions) => handleApply(resolutions)} />
      )}
    </div>
  );
}
