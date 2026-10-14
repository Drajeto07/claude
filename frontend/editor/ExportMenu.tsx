"use client";

import { AlertTriangle, Download, FileDown, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { JobProgressBar } from "@/components/JobProgressBar";
import { useExport } from "@/editor/useExport";
import { useI18n } from "@/i18n/I18nProvider";
import { format as fill } from "@/i18n/locales";
import type { FidelityReport } from "@/types/document";

type Format = "docx" | "pdf";

function Checkbox({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex items-center gap-2 text-sm text-foreground">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4 rounded accent-[var(--accent)]" />
      {label}
    </label>
  );
}

/** What the export's check found: the file read back against the document. */
export function ExportResult({ report }: { report: FidelityReport }) {
  const { m } = useI18n();
  const t = m.edExport;
  const review = report.items.filter((item) => item.policy === "lossy" || item.policy === "unsupported" || item.policy === "blocked");
  let headline = t.unchecked;
  if (report.contentStatus === "verified") headline = report.contentLossCount > 0 ? t.verifiedLoss : t.verified;
  else if (report.contentStatus === "changed") headline = t.changed;
  const good = report.contentStatus === "verified" && report.contentLossCount === 0;
  return (
    <div role="status" className={`mt-3 rounded-lg border p-2 text-xs ${good ? "border-success/30 bg-success/10 text-foreground" : "border-warning/40 bg-warning-soft text-foreground"}`}>
      <p className="flex items-start gap-1.5 font-medium">
        {good ? <ShieldCheck className="mt-px h-3.5 w-3.5 shrink-0 text-success" aria-hidden="true" /> : <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />}
        {headline}
      </p>
      {report.contentStatus === "changed" && report.content && (
        <ul className="mt-1 ml-5 list-disc">
          {report.content.samples.slice(0, 5).map((sample, index) => (
            <li key={index}>{sample.source || sample.result}</li>
          ))}
        </ul>
      )}
      {review.length > 0 && (
        <ul className="mt-1 ml-5 list-disc">
          {review.map((item) => (
            <li key={`${item.feature}:${item.reason}`}>
              {item.reason}
              {item.count > 1 && ` (×${item.count})`}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The Export menu: format, what to include, and the export's real progress
 * (useExport). The 3 checkboxes are export-time-only overrides (see
 * build_docx/build_pdf's docstrings): they never change the document's own
 * settings, so exporting once without page numbers doesn't turn them off.
 * After a download it stays open with what the export's check found.
 */
export function ExportMenu({ documentId, flush }: { documentId: string; flush: () => Promise<unknown> }) {
  const { m } = useI18n();
  const t = m.edExport;
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<Format>("docx");
  const [includePageBreaks, setIncludePageBreaks] = useState(true);
  const [includeHeaders, setIncludeHeaders] = useState(true);
  const [includePageNumbers, setIncludePageNumbers] = useState(true);
  const { exportAs, progress, exporting, error, report } = useExport(documentId, flush);

  async function handleExport() {
    await exportAs(format, { includeHeaders, includePageNumbers, includePageBreaks });
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-full border border-line-strong px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-accent hover:text-accent"
      >
        <FileDown className="h-3.5 w-3.5" aria-hidden="true" />
        {t.button}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => !exporting && setOpen(false)} />
          <div className="absolute right-0 top-full z-50 mt-2 w-64 rounded-xl border border-line bg-surface p-4 text-left shadow-pop">
            <p className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t.format}</p>
            <div className="mb-3 flex gap-2">
              {(["docx", "pdf"] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  disabled={exporting}
                  onClick={() => setFormat(option)}
                  aria-pressed={format === option}
                  className={`flex-1 rounded-lg border px-2 py-1.5 text-sm font-medium transition-colors disabled:opacity-60 ${
                    format === option ? "border-accent bg-accent-soft text-accent" : "border-line text-foreground hover:bg-surface-muted"
                  }`}
                >
                  {option.toUpperCase()}
                </button>
              ))}
            </div>

            <p className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t.include}</p>
            <div className="mb-4 flex flex-col gap-2">
              <Checkbox checked={includePageBreaks} onChange={setIncludePageBreaks} label={t.pageBreaks} />
              <Checkbox checked={includeHeaders} onChange={setIncludeHeaders} label={t.headers} />
              <Checkbox checked={includePageNumbers} onChange={setIncludePageNumbers} label={t.pageNumbers} />
            </div>

            <button
              type="button"
              onClick={() => void handleExport()}
              disabled={exporting}
              className="flex w-full items-center justify-center gap-1.5 rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              {exporting ? t.exporting : fill(t.download, { format: format.toUpperCase() })}
            </button>
            {progress && (
              <div className="mt-3">
                <JobProgressBar progress={progress} />
              </div>
            )}
            {error && <p className="mt-3 text-xs text-danger">{error}</p>}
            {report && !exporting && <ExportResult report={report} />}
          </div>
        </>
      )}
    </div>
  );
}
