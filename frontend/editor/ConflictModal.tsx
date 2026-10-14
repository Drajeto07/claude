"use client";

import { AlertTriangle, Check, RotateCcw } from "lucide-react";
import { useState } from "react";

import { JobProgressBar } from "@/components/JobProgressBar";
import { useI18n } from "@/i18n/I18nProvider";
import { plural } from "@/i18n/locales";
import type { ConflictResolution, ConflictResolutionChoice, FormattingConflict, JobProgress } from "@/types/document";

function formatValue(value: string, unit: string | null): string {
  return unit ? `${value}${unit}` : value;
}

/**
 * Spec §7.10, full literal design (confirmed with Boril rather than the
 * lighter toast alternative): one Required/Current comparison per conflict,
 * each with its own Apply-recommended/Keep-current choice. "Continue" stays
 * disabled until every conflict has a choice, since a partially-resolved
 * submission has no well-defined meaning. `progress`: the formatting job the
 * choices started, while it runs (the dialog closes once it has applied).
 */
export function ConflictModal({
  conflicts,
  onResolve,
  onCancel,
  progress,
}: {
  conflicts: FormattingConflict[];
  onResolve: (resolutions: ConflictResolution[]) => void;
  onCancel: () => void;
  progress: JobProgress | null;
}) {
  const { m } = useI18n();
  const t = m.edConflict;
  const [choices, setChoices] = useState<Record<number, ConflictResolutionChoice>>({});

  const allResolved = conflicts.every((_, index) => choices[index]);
  const applying = progress !== null;
  const choiceClass = (on: boolean) =>
    `flex items-center gap-1 rounded-lg px-3 py-1 text-xs font-medium ${on ? "bg-accent text-accent-foreground" : "bg-surface-muted text-foreground hover:bg-line"}`;

  function submit() {
    onResolve(
      conflicts.map((conflict, index) => ({
        elementId: conflict.elementId,
        property: conflict.property,
        resolution: choices[index],
      })),
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="conflict-title" className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-line bg-surface p-5 shadow-pop">
        <h2 id="conflict-title" className="mb-1 flex items-center gap-2 text-lg font-semibold text-foreground">
          <AlertTriangle className="h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
          {plural(conflicts.length, t.title)}
        </h2>
        <p className="mb-4 text-sm text-muted">{t.intro}</p>
        <div className="flex flex-col gap-3">
          {conflicts.map((conflict, index) => (
            <div key={`${conflict.elementId}-${conflict.property}`} className="rounded-xl border border-warning/40 bg-warning-soft p-3 text-sm">
              <p className="mb-1.5 font-medium text-foreground">{conflict.property}</p>
              <p className="text-muted">
                {t.required} <span className="font-medium text-foreground">{formatValue(conflict.requiredValue, conflict.requiredUnit)}</span>
              </p>
              <p className="mb-2 text-muted">
                {t.current} <span className="font-medium text-foreground">{formatValue(conflict.currentValue, conflict.currentUnit)}</span>
              </p>
              <div className="flex gap-2">
                <button type="button" onClick={() => setChoices((prev) => ({ ...prev, [index]: "apply_recommended" }))} className={choiceClass(choices[index] === "apply_recommended")}>
                  <Check className="h-3.5 w-3.5" aria-hidden="true" />
                  {t.applyRecommended}
                </button>
                <button type="button" onClick={() => setChoices((prev) => ({ ...prev, [index]: "keep_current" }))} className={choiceClass(choices[index] === "keep_current")}>
                  <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                  {t.keepCurrent}
                </button>
              </div>
            </div>
          ))}
        </div>
        {progress && (
          <div className="mt-4">
            <JobProgressBar progress={progress} />
          </div>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel} disabled={applying} className="rounded-lg px-4 py-2 text-sm text-muted hover:text-foreground disabled:opacity-50">
            {t.cancel}
          </button>
          <button
            type="button"
            disabled={!allResolved || applying}
            onClick={submit}
            className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            {applying ? t.applying : t.continue}
          </button>
        </div>
      </div>
    </div>
  );
}
