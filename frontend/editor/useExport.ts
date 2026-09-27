"use client";

import { useState } from "react";

import { errorMessage, exportDocument, jobFileUrl, type ExportOptions } from "@/services/api";
import type { ExportJobResult, FidelityReport, JobProgress } from "@/types/document";

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
 * Exporting the document: pending typing is saved first (`flush`), so the file
 * has exactly what is on screen; then an export job renders it, reporting its
 * real progress, and the browser downloads the result. `report` is the export's
 * fidelity report: what it approximated or left out, and whether the file, read
 * back, holds every word of the document.
 */
export function useExport(documentId: string, flush: () => Promise<unknown>) {
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<FidelityReport | null>(null);

  /** true once the download has started. */
  async function exportAs(format: "docx" | "pdf", options: ExportOptions): Promise<boolean> {
    setError(null);
    setReport(null);
    setProgress({ stage: "queued", progress: 0 });
    try {
      await flush();
      const job = await exportDocument(documentId, format, options, setProgress);
      download(jobFileUrl(job.id));
      setReport((job.result as ExportJobResult | null)?.fidelity ?? null);
      return true;
    } catch (err) {
      setError(errorMessage(err, "The export failed. Please try again."));
      return false;
    } finally {
      setProgress(null);
    }
  }

  return { exportAs, progress, exporting: progress !== null, error, report };
}
