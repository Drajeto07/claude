"use client";

import { useId, useState } from "react";

import type { Document } from "@/types/document";

export type TrackedChanges = NonNullable<Document["trackedChanges"]>;

const OPTIONS: { value: TrackedChanges; label: string; detail: string }[] = [
  { value: "kept", label: "Keep them in the Word export", detail: "In every part you don't change or restyle here, still to review in Word." },
  { value: "accepted", label: "Accept them all", detail: "No export has them: the document is as it's shown here." },
];

/**
 * What happens to a Word file's tracked changes (tracker DOCX-022). The app shows them
 * as if accepted either way; whether a Word export keeps them or they are all accepted
 * is the person's choice, never made for them.
 */
export function TrackedChangesChoice({ choice, onChoose }: { choice: TrackedChanges; onChoose: (choice: TrackedChanges) => Promise<unknown> }) {
  const name = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function choose(next: TrackedChanges) {
    if (next === choice || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onChoose(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't change what happens to the tracked changes.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <fieldset disabled={busy} className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <legend className="px-1 text-sm font-semibold text-zinc-800 dark:text-zinc-200">Tracked changes</legend>
      <p className="mb-2 text-xs text-zinc-600 dark:text-zinc-400">This Word file has tracked changes. They&rsquo;re shown here as if accepted.</p>
      <div className="flex flex-col gap-1.5">
        {OPTIONS.map((option) => (
          <label key={option.value} className="flex items-start gap-2 text-sm text-zinc-700 dark:text-zinc-300">
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={choice === option.value}
              onChange={() => choose(option.value)}
              className="mt-0.5 h-4 w-4 border-zinc-300 text-accent focus:ring-accent dark:border-zinc-700"
            />
            <span>
              {option.label}
              <span className="block text-xs text-zinc-500">{option.detail}</span>
            </span>
          </label>
        ))}
      </div>
      {error && (
        <p role="alert" className="mt-2 text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
    </fieldset>
  );
}
