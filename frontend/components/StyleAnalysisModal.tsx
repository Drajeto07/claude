"use client";

import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { analyzeStyle } from "@/services/api";
import type { Document, StyleAnalysisResult } from "@/types/document";

function elementPreview(document: Document, elementId: string): string {
  const element = document.elements.find((el) => el.id === elementId);
  const text = element?.content ?? "";
  return text.length > 80 ? `${text.slice(0, 80)}...` : text;
}

/**
 * Read-only writing-style report (spec: AI must never auto-rewrite) --
 * triggered by the bottom bar's Провери-стила/Анализирай-текста buttons.
 * Same modal shell as ConflictModal.tsx for visual consistency. Renders
 * three genuinely different states (ok / empty_document / ai_unavailable)
 * from StyleAnalysisResponse.status, never a fake "analyzing..." result.
 */
export function StyleAnalysisModal({ document, onClose }: { document: Document; onClose: () => void }) {
  const [result, setResult] = useState<StyleAnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    analyzeStyle(document.id)
      .then((r) => {
        if (!cancelled) setResult(r);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to analyze style.");
      });
    return () => {
      cancelled = true;
    };
  }, [document.id]);

  const isConsistent = (result?.consistencyScore ?? 0) >= 0.7;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-5 shadow-xl dark:bg-zinc-900">
        <h2 className="mb-1 text-lg font-semibold text-zinc-900 dark:text-zinc-100">Style analysis</h2>
        <p className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">
          A read-only look at tone and voice consistency across the document&rsquo;s text &mdash; nothing here is changed automatically.
        </p>

        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

        {!result && !error && (
          <div className="flex items-center justify-center gap-2 py-8 text-sm text-zinc-500 dark:text-zinc-400">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Analyzing...
          </div>
        )}

        {result?.status === "empty_document" && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">Not enough text in this document yet to analyze.</p>
        )}

        {result?.status === "ai_unavailable" && (
          <p className="text-sm text-amber-700 dark:text-amber-400">Style analysis isn&rsquo;t available right now (no AI provider configured on the server).</p>
        )}

        {result?.status === "ok" && (
          <div className="flex flex-col gap-4">
            <div
              className={`rounded-lg border p-3 ${
                isConsistent
                  ? "border-green-200 bg-green-50 dark:border-green-900 dark:bg-green-950/30"
                  : "border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/30"
              }`}
            >
              <p className={`flex items-center gap-1.5 text-sm font-medium ${isConsistent ? "text-green-800 dark:text-green-300" : "text-amber-800 dark:text-amber-300"}`}>
                {isConsistent ? <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" /> : <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />}
                Consistency: {Math.round((result.consistencyScore ?? 0) * 100)}%
              </p>
              <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">Tone: {result.tone}</p>
              <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">{result.summary}</p>
            </div>

            {result.flagged.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-semibold tracking-wide text-zinc-400 uppercase dark:text-zinc-500">Flagged paragraphs</p>
                <div className="flex flex-col gap-2">
                  {result.flagged.map((flag) => (
                    <div key={flag.elementId} className="rounded border border-zinc-200 p-2.5 text-sm dark:border-zinc-700">
                      <p className="text-zinc-700 dark:text-zinc-300">&ldquo;{elementPreview(document, flag.elementId)}&rdquo;</p>
                      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{flag.reason}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <div className="mt-5 flex justify-end">
          <button type="button" onClick={onClose} className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
