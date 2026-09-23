"use client";

import { AlertTriangle, Check, RotateCcw } from "lucide-react";
import { useState } from "react";

import type { ConflictResolution, ConflictResolutionChoice, FormattingConflict } from "@/types/document";

function formatValue(value: string, unit: string | null): string {
  return unit ? `${value}${unit}` : value;
}

/**
 * Spec §7.10, full literal design (confirmed with Boril rather than the
 * lighter toast alternative): one Required/Current comparison per conflict,
 * each with its own Apply-recommended/Keep-current choice. "Continue" stays
 * disabled until every conflict has a choice, since a partially-resolved
 * submission has no well-defined meaning.
 */
export function ConflictModal({
  conflicts,
  onResolve,
  onCancel,
}: {
  conflicts: FormattingConflict[];
  onResolve: (resolutions: ConflictResolution[]) => void;
  onCancel: () => void;
}) {
  const [choices, setChoices] = useState<Record<number, ConflictResolutionChoice>>({});

  const allResolved = conflicts.every((_, index) => choices[index]);

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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-5 shadow-xl dark:bg-zinc-900">
        <h2 className="mb-1 flex items-center gap-2 text-lg font-semibold text-zinc-900 dark:text-zinc-100">
          <AlertTriangle className="h-5 w-5 shrink-0 text-amber-500" aria-hidden="true" />
          Formatting conflict{conflicts.length > 1 ? "s" : ""}
        </h2>
        <p className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">
          What you&apos;re applying would change something you already set manually. Choose what to keep for each.
        </p>
        <div className="flex flex-col gap-3">
          {conflicts.map((conflict, index) => (
            <div key={`${conflict.elementId}-${conflict.property}`} className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-900 dark:bg-amber-950/30">
              <p className="mb-1.5 font-medium text-zinc-700 dark:text-zinc-300">{conflict.property}</p>
              <p className="text-zinc-600 dark:text-zinc-400">
                Required: <span className="font-medium text-zinc-800 dark:text-zinc-200">{formatValue(conflict.requiredValue, conflict.requiredUnit)}</span>
              </p>
              <p className="mb-2 text-zinc-600 dark:text-zinc-400">
                Current: <span className="font-medium text-zinc-800 dark:text-zinc-200">{formatValue(conflict.currentValue, conflict.currentUnit)}</span>
              </p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setChoices((prev) => ({ ...prev, [index]: "apply_recommended" }))}
                  className={`flex items-center gap-1 rounded px-3 py-1 text-xs font-medium ${
                    choices[index] === "apply_recommended"
                      ? "bg-accent text-accent-foreground"
                      : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
                  }`}
                >
                  <Check className="h-3.5 w-3.5" aria-hidden="true" />
                  Apply recommended
                </button>
                <button
                  type="button"
                  onClick={() => setChoices((prev) => ({ ...prev, [index]: "keep_current" }))}
                  className={`flex items-center gap-1 rounded px-3 py-1 text-xs font-medium ${
                    choices[index] === "keep_current"
                      ? "bg-accent text-accent-foreground"
                      : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
                  }`}
                >
                  <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                  Keep current
                </button>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="rounded px-4 py-2 text-sm text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300">
            Cancel
          </button>
          <button
            type="button"
            disabled={!allResolved}
            onClick={submit}
            className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            Continue
          </button>
        </div>
      </div>
    </div>
  );
}
