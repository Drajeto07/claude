"use client";

import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import { analyzeStyle } from "@/services/api";
import type { Document, StyleAnalysisResult } from "@/types/document";

function elementPreview(document: Document, elementId: string): string {
  const element = document.elements.find((el) => el.id === elementId);
  const text = element?.content ?? "";
  return text.length > 80 ? `${text.slice(0, 80)}...` : text;
}

/**
 * Read-only writing-style report (spec: AI must never auto-rewrite) --
 * triggered by the bottom bar's "Check the style" button.
 * Same modal shell as ConflictModal.tsx for visual consistency. Renders
 * three genuinely different states (ok / empty_document / ai_unavailable)
 * from StyleAnalysisResponse.status, never a fake "analyzing..." result.
 */
export function StyleAnalysisModal({ document, onClose }: { document: Document; onClose: () => void }) {
  const { m } = useI18n();
  const t = m.edStyle;
  const [result, setResult] = useState<StyleAnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    analyzeStyle(document.id)
      .then((r) => {
        if (!cancelled) setResult(r);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : t.failed);
      });
    return () => {
      cancelled = true;
    };
  }, [document.id, t.failed]);

  const isConsistent = (result?.consistencyScore ?? 0) >= 0.7;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="style-title" className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-line bg-surface p-5 shadow-pop">
        <h2 id="style-title" className="mb-1 text-lg font-semibold text-foreground">
          {t.title}
        </h2>
        <p className="mb-4 text-sm text-muted">{t.intro}</p>

        {error && <p className="text-sm text-danger">{error}</p>}

        {!result && !error && (
          <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            {t.analyzing}
          </div>
        )}

        {result?.status === "empty_document" && <p className="text-sm text-muted">{t.empty}</p>}

        {result?.status === "ai_unavailable" && <p className="text-sm text-warning">{t.unavailable}</p>}

        {result?.status === "ok" && (
          <div className="flex flex-col gap-4">
            <div className={`rounded-xl border p-3 ${isConsistent ? "border-success/30 bg-success/10" : "border-warning/40 bg-warning-soft"}`}>
              <p className={`flex items-center gap-1.5 text-sm font-medium ${isConsistent ? "text-success" : "text-warning"}`}>
                {isConsistent ? <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" /> : <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />}
                {format(t.consistency, { percent: Math.round((result.consistencyScore ?? 0) * 100) })}
              </p>
              <p className="mt-1 text-xs text-muted">{format(t.tone, { tone: result.tone ?? "" })}</p>
              <p className="mt-1 text-xs text-muted">{result.summary}</p>
            </div>

            {result.flagged.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t.flagged}</p>
                <div className="flex flex-col gap-2">
                  {result.flagged.map((flag) => (
                    <div key={flag.elementId} className="rounded-lg border border-line p-2.5 text-sm">
                      <p className="text-foreground">“{elementPreview(document, flag.elementId)}”</p>
                      <p className="mt-1 text-xs text-muted">{flag.reason}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <div className="mt-5 flex justify-end">
          <button type="button" onClick={onClose} className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90">
            {t.close}
          </button>
        </div>
      </div>
    </div>
  );
}
