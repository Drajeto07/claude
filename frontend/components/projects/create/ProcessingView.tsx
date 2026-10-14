"use client";

import { CheckCircle2, Circle, Loader2 } from "lucide-react";

import { useI18n } from "@/i18n/I18nProvider";
import type { JobProgress } from "@/types/document";

export type StageKey = "uploading" | "parsing" | "analyzing" | "finalizing" | "instructions" | "formatting";

/** A step of the work as the backend job names it (app/jobs), and what it is called on screen. */
export type ProcessingStage = { stage: string; key: StageKey };

/** `reached`: the furthest stage the job has got to (-1 before the first), so a late "queued"
 * report never moves a finished stage back. */
export type Processing = { title: "importTitle" | "formatTitle"; stages: ProcessingStage[]; current: JobProgress; reached: number };

/** The stages an import goes through, in order (a Word file isn't analysed; a text file isn't parsed). */
export function importStages(method: "paste" | "upload", file: File | null): ProcessingStage[] {
  const extension = file?.name.split(".").pop()?.toLowerCase();
  if (method === "paste") return [{ stage: "analyzing", key: "analyzing" }, { stage: "finalizing", key: "finalizing" }];
  return [
    { stage: "uploading", key: "uploading" },
    ...(extension === "txt" ? [] : [{ stage: "parsing", key: "parsing" } as const]),
    ...(extension === "docx" ? [] : [{ stage: "analyzing", key: "analyzing" } as const]),
    { stage: "finalizing", key: "finalizing" },
  ];
}

export function formatStages(withInstructions: boolean): ProcessingStage[] {
  return [...(withInstructions ? [{ stage: "analyzing", key: "instructions" } as const] : []), { stage: "formatting", key: "formatting" }];
}

/** Where a job's report puts it: a stage once reached stays reached. */
export function advance(processing: Omit<Processing, "current" | "reached"> & { reached?: number }, current: JobProgress): Processing {
  const index = current.stage === "complete" ? processing.stages.length : processing.stages.findIndex((stage) => stage.stage === current.stage);
  return { ...processing, current, reached: Math.max(processing.reached ?? -1, index) };
}

/** What the backend job is really doing: the stage and percentage it records, polled -- never a timer. */
export function ProcessingView({ processing }: { processing: Processing }) {
  const { m } = useI18n();
  const t = m.create.processing;
  const { stages, current, reached } = processing;
  const title = t[processing.title];

  return (
    <div className="mx-auto flex w-full max-w-sm flex-col gap-6 py-12">
      <h1 className="text-center text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
      <ol className="flex flex-col gap-3">
        {stages.map((stage, index) => {
          const done = index < reached;
          const active = index === reached;
          return (
            <li key={stage.key} className="flex items-center gap-3 text-sm">
              {done ? (
                <CheckCircle2 className="h-5 w-5 shrink-0 text-success" aria-hidden="true" />
              ) : active ? (
                <Loader2 className="h-5 w-5 shrink-0 animate-spin text-accent" aria-hidden="true" />
              ) : (
                <Circle className="h-5 w-5 shrink-0 text-line-strong" aria-hidden="true" />
              )}
              <span className={done || active ? "text-foreground" : "text-muted"}>{t.stages[stage.key]}</span>
            </li>
          );
        })}
      </ol>
      <div>
        <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={current.progress} aria-label={title} className="h-1.5 overflow-hidden rounded-full bg-surface-muted">
          <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${current.progress}%` }} />
        </div>
        <p className="mt-2 text-center text-xs text-muted">{reached < 0 ? t.waiting : `${current.progress}%`}</p>
      </div>
    </div>
  );
}
