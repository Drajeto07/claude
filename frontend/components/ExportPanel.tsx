"use client";

import { Download, FileDown } from "lucide-react";
import { useState } from "react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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

/**
 * Same plain-<a>-download approach the old version used (a GET with
 * Content-Disposition: attachment is all a browser needs, no fetch+blob
 * dance) -- just with the href built from the chosen format + checkbox
 * state instead of a fixed URL. The 3 checkboxes are export-time-only
 * overrides (see build_docx/build_pdf's docstrings): they never change the
 * document's own persisted settings, so exporting once without page
 * numbers doesn't turn them off for next time.
 */
export function ExportPanel({ documentId }: { documentId: string }) {
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<Format>("docx");
  const [includePageBreaks, setIncludePageBreaks] = useState(true);
  const [includeHeaders, setIncludeHeaders] = useState(true);
  const [includePageNumbers, setIncludePageNumbers] = useState(true);

  const params = new URLSearchParams({
    includePageBreaks: String(includePageBreaks),
    includeHeaders: String(includeHeaders),
    includePageNumbers: String(includePageNumbers),
  });
  const href = `${API_BASE_URL}/api/documents/${documentId}/export/${format}?${params}`;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-full border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:border-accent hover:text-accent dark:border-zinc-700 dark:text-zinc-300"
      >
        <FileDown className="h-3.5 w-3.5" aria-hidden="true" />
        Export
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full z-50 mt-2 w-64 rounded-lg border border-zinc-200 bg-white p-4 text-left shadow-lg dark:border-zinc-800 dark:bg-zinc-900">
            <p className="mb-2 text-xs font-semibold tracking-wide text-zinc-400 uppercase dark:text-zinc-500">Format</p>
            <div className="mb-3 flex gap-2">
              <button
                type="button"
                onClick={() => setFormat("docx")}
                className={`flex-1 rounded border px-2 py-1.5 text-sm font-medium transition-colors ${
                  format === "docx" ? "border-accent bg-accent/5 text-accent" : "border-zinc-200 text-zinc-600 dark:border-zinc-700 dark:text-zinc-400"
                }`}
              >
                DOCX
              </button>
              <button
                type="button"
                onClick={() => setFormat("pdf")}
                className={`flex-1 rounded border px-2 py-1.5 text-sm font-medium transition-colors ${
                  format === "pdf" ? "border-accent bg-accent/5 text-accent" : "border-zinc-200 text-zinc-600 dark:border-zinc-700 dark:text-zinc-400"
                }`}
              >
                PDF
              </button>
            </div>

            <p className="mb-2 text-xs font-semibold tracking-wide text-zinc-400 uppercase dark:text-zinc-500">Include</p>
            <div className="mb-4 flex flex-col gap-2">
              <Checkbox checked={includePageBreaks} onChange={setIncludePageBreaks} label="Page breaks" />
              <Checkbox checked={includeHeaders} onChange={setIncludeHeaders} label="Headers & footer" />
              <Checkbox checked={includePageNumbers} onChange={setIncludePageNumbers} label="Page numbers" />
            </div>

            <a
              href={href}
              onClick={() => setOpen(false)}
              className="flex items-center justify-center gap-1.5 rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90"
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              Download {format.toUpperCase()}
            </a>
          </div>
        </>
      )}
    </div>
  );
}
