"use client";

import { useId, useState } from "react";

import { ApiError } from "@/services/api/client";
import type { Document } from "@/types/document";

export type TrackedChanges = NonNullable<Document["trackedChanges"]>;

const OPTIONS: { value: TrackedChanges; label: string; detail: string }[] = [
  { value: "kept", label: "Keep them in the Word export", detail: "In every part you don't change or restyle here, still to review in Word." },
  { value: "accepted", label: "Accept them all", detail: "No export has them: the document is as it's shown here." },
  {
    value: "rejected",
    label: "Reject them all",
    detail: "Deleted text comes back, inserted text goes and formatting changes are undone: the document is read again from the Word file.",
  },
];

/**
 * What happens to a Word file's tracked changes (tracker DOCX-022, DOCX-022A). The app shows them
 * as if accepted; whether a Word export keeps them, they are all accepted, or all rejected is the
 * person's choice, never made for them. Rejecting reads the document again from the file: when
 * that would replace changes made here, the server says so and the person is asked first.
 */
export function TrackedChangesChoice({
  choice,
  onChoose,
}: {
  choice: TrackedChanges;
  onChoose: (choice: TrackedChanges, discardEdits?: boolean) => Promise<unknown>;
}) {
  const name = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function choose(next: TrackedChanges) {
    if (next === choice || busy) return;
    setBusy(true);
    setError(null);
    try {
      try {
        await onChoose(next);
      } catch (err) {
        if (!(err instanceof ApiError && err.code === "edits_would_be_lost")) throw err;
        if (window.confirm(err.message)) await onChoose(next, true);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't change what happens to the tracked changes.");
    } finally {
      setBusy(false);
    }
  }

  if (choice === "rejected") {
    return (
      <section className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
        <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">Tracked changes</h3>
        <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">
          They were rejected: the document was read again from the Word file without them. Undo brings them back.
        </p>
      </section>
    );
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
