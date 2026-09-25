"use client";

import { Download, FileDown } from "lucide-react";
import { useState } from "react";

import { JobProgressBar } from "@/components/JobProgressBar";
import { exportDocument, jobFileUrl } from "@/services/api";
import type { JobProgress } from "@/types/document";

type Format = "docx" | "pdf";

function Checkbox({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-zinc-300 text-accent focus:ring-accent dark:border-zinc-700"
      />
      {label}
    </label>
  );
}

/** Starts the browser's download of a finished export (sent as an attachment,
 * so the page stays where it is). */
function download(url: string) {
  const link = window.document.createElement("a");
  link.href = url;
  link.rel = "noopener";
  window.document.body.appendChild(link);
  link.click();
  link.remove();
}

/**
 * The file is rendered in a background job (корекции.docx §52) whose real
 * progress shows here, then downloaded. Unsaved typing is saved first
 * (`onBeforeExport`), so the file has exactly what is on screen. The 3
 * checkboxes are export-time-only overrides (see build_docx/build_pdf's
 * docstrings): they never change the document's own settings, so exporting
 * once without page numbers doesn't turn them off for next time.
 */
export function ExportPanel({ documentId, onBeforeExport }: { documentId: string; onBeforeExport: () => Promise<unknown> }) {
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<Format>("docx");
  const [includePageBreaks, setIncludePageBreaks] = useState(true);
  const [includeHeaders, setIncludeHeaders] = useState(true);
  const [includePageNumbers, setIncludePageNumbers] = useState(true);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const exporting = progress !== null;

  async function handleExport() {
    setError(null);
    setProgress({ stage: "queued", progress: 0 });
    try {
      await onBeforeExport();
      const job = await exportDocument(documentId, format, { includeHeaders, includePageNumbers, includePageBreaks }, setProgress);
      download(jobFileUrl(job.id));
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The export failed. Please try again.");
    } finally {
      setProgress(null);
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-full border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:border-accent hover:text-accent dark:border-zinc-700 dark:text-zinc-300"
      >
        <FileDown className="h-3.5 w-3.5" aria-hidden="true" />
        Export
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => !exporting && setOpen(false)} />
          <div className="absolute right-0 top-full z-50 mt-2 w-64 rounded-lg border border-zinc-200 bg-white p-4 text-left shadow-lg dark:border-zinc-800 dark:bg-zinc-900">
            <p className="mb-2 text-xs font-semibold tracking-wide text-zinc-400 uppercase dark:text-zinc-500">Format</p>
            <div className="mb-3 flex gap-2">
              {(["docx", "pdf"] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  disabled={exporting}
                  onClick={() => setFormat(option)}
                  aria-pressed={format === option}
                  className={`flex-1 rounded border px-2 py-1.5 text-sm font-medium transition-colors disabled:opacity-60 ${
                    format === option ? "border-accent bg-accent/5 text-accent" : "border-zinc-200 text-zinc-600 dark:border-zinc-700 dark:text-zinc-400"
                  }`}
                >
                  {option.toUpperCase()}
                </button>
              ))}
            </div>

            <p className="mb-2 text-xs font-semibold tracking-wide text-zinc-400 uppercase dark:text-zinc-500">Include</p>
            <div className="mb-4 flex flex-col gap-2">
              <Checkbox checked={includePageBreaks} onChange={setIncludePageBreaks} label="Page breaks" />
              <Checkbox checked={includeHeaders} onChange={setIncludeHeaders} label="Headers & footer" />
              <Checkbox checked={includePageNumbers} onChange={setIncludePageNumbers} label="Page numbers" />
            </div>

            <button
              type="button"
              onClick={() => void handleExport()}
              disabled={exporting}
              className="flex w-full items-center justify-center gap-1.5 rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              {exporting ? "Exporting…" : `Download ${format.toUpperCase()}`}
            </button>
            {progress && (
              <div className="mt-3">
                <JobProgressBar progress={progress} />
              </div>
            )}
            {error && <p className="mt-3 text-xs text-red-600 dark:text-red-400">{error}</p>}
          </div>
        </>
      )}
    </div>
  );
}
