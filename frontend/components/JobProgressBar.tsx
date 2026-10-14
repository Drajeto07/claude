"use client";

import { Loader2 } from "lucide-react";

import { useI18n } from "@/i18n/I18nProvider";
import type { JobProgress } from "@/types/document";

/**
 * A background job's real stage and percentage (корекции.docx §53), as the
 * backend records them and services/api.ts polls them -- never a timer.
 * `label` names the work, e.g. "Reading report.docx".
 */
export function JobProgressBar({ progress, label }: { progress: JobProgress; label?: string }) {
  const { m } = useI18n();
  const stages: Record<string, string> = m.jobs.stages;
  const stage = stages[progress.stage] ?? m.jobs.working;
  return (
    <div role="status" className="flex flex-col gap-1">
      <p className="flex items-center gap-1.5 text-xs text-muted">
        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden="true" />
        <span className="truncate">
          {label && `${label} · `}
          {stage}
          {progress.stage === "queued" ? "…" : ` · ${progress.progress}%`}
        </span>
      </p>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress.progress}
        aria-label={label ?? stage}
        className="h-1 overflow-hidden rounded-full bg-surface-muted"
      >
        <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${progress.progress}%` }} />
      </div>
    </div>
  );
}
