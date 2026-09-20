"use client";

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
        <h2 className="mb-1 text-lg font-semibold text-zinc-900 dark:text-zinc-100">
          Formatting conflict{conflicts.length > 1 ? "s" : ""}
        </h2>
        <p className="mb-4 text-sm text-zinc-500 dark:text-zinc-400">
          What you&apos;re applying would change something you already set manually. Choose what to keep for each.
        </p>
        <div className="flex flex-col gap-3">
          {conflicts.map((conflict, index) => (
            <div key={`${conflict.elementId}-${conflict.property}`} className="rounded border border-zinc-200 p-3 text-sm dark:border-zinc-700">
              <p className="mb-1 font-medium text-zinc-700 dark:text-zinc-300">{conflict.property}</p>
              <p className="text-zinc-500 dark:text-zinc-400">Required: {formatValue(conflict.requiredValue, conflict.requiredUnit)}</p>
              <p className="mb-2 text-zinc-500 dark:text-zinc-400">Current: {formatValue(conflict.currentValue, conflict.currentUnit)}</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setChoices((prev) => ({ ...prev, [index]: "apply_recommended" }))}
                  className={`rounded px-3 py-1 text-xs font-medium ${
                    choices[index] === "apply_recommended"
                      ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                      : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
                  }`}
                >
                  Apply recommended
                </button>
                <button
                  type="button"
                  onClick={() => setChoices((prev) => ({ ...prev, [index]: "keep_current" }))}
                  className={`rounded px-3 py-1 text-xs font-medium ${
                    choices[index] === "keep_current"
                      ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                      : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
                  }`}
                >
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
            className="rounded-full bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
          >
            Continue
          </button>
        </div>
      </div>
    </div>
  );
}
