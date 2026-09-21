"use client";

import { Redo2, Undo2 } from "lucide-react";
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
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Template</span>
          <select
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
            className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 focus:border-accent focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          >
            <option value="">No template</option>
            {templates.map((template) => (
              <option key={template.id} value={template.id}>
                {template.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Instructions</span>
          <textarea
            value={instructionsText}
            onChange={(e) => setInstructionsText(e.target.value)}
            rows={3}
            placeholder="e.g. &quot;make headings red and Arial&quot;"
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
          onClick={() => handleApply()}
          disabled={isApplying}
          className="rounded-full bg-accent px-6 py-2.5 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isApplying ? "Applying..." : "Apply formatting"}
        </button>
        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
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

      {conflicts && (
        <ConflictModal conflicts={conflicts} onCancel={() => setConflicts(null)} onResolve={(resolutions) => handleApply(resolutions)} />
      )}
    </div>
  );
}
