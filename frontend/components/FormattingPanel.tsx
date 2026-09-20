"use client";

import { useEffect, useState } from "react";

import { formatDocument, listTemplates } from "@/services/api";
import type { Document, TemplateSummary } from "@/types/document";

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
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch(() => setError("Could not load templates. Is the backend running on port 8000?"));
  }, []);

  async function handleApply() {
    setError(null);
    setIsApplying(true);
    try {
      const updated = await formatDocument(document.id, {
        templateId: templateId || undefined,
        instructionsText: instructionsText.trim() || undefined,
        instructionsFile: instructionsFile ?? undefined,
      });
      onFormatted(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not apply formatting.");
    } finally {
      setIsApplying(false);
    }
  }

  return (
    <div className="mb-6 rounded-lg border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900/50">
      <h2 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Formatting</h2>
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
          onClick={handleApply}
          disabled={isApplying}
          className="rounded-full bg-zinc-900 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          {isApplying ? "Applying..." : "Apply formatting"}
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
    </div>
  );
}
