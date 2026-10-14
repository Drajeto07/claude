"use client";

import { useId, useState } from "react";

import { useI18n } from "@/i18n/I18nProvider";
import { ApiError } from "@/services/api/client";
import type { Document } from "@/types/document";

export type TrackedChanges = NonNullable<Document["trackedChanges"]>;

const OPTIONS: TrackedChanges[] = ["kept", "accepted", "rejected"];

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
  const { m } = useI18n();
  const t = m.trackedChanges;
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
      setError(err instanceof Error ? err.message : t.failed);
    } finally {
      setBusy(false);
    }
  }

  if (choice === "rejected") {
    return (
      <section className="rounded-xl border border-line bg-surface p-3">
        <h3 className="text-sm font-semibold text-foreground">{t.title}</h3>
        <p className="mt-1 text-xs text-muted">{t.rejectedNote}</p>
      </section>
    );
  }

  return (
    <fieldset disabled={busy} className="rounded-xl border border-line bg-surface p-3">
      <legend className="px-1 text-sm font-semibold text-foreground">{t.title}</legend>
      <p className="mb-2 text-xs text-muted">{t.intro}</p>
      <div className="flex flex-col gap-1.5">
        {OPTIONS.map((option) => (
          <label key={option} className="flex items-start gap-2 text-sm text-foreground">
            <input type="radio" name={name} value={option} checked={choice === option} onChange={() => choose(option)} className="mt-0.5 h-4 w-4 accent-[var(--accent)]" />
            <span>
              {t.options[option].label}
              <span className="block text-xs text-muted">{t.options[option].detail}</span>
            </span>
          </label>
        ))}
      </div>
      {error && (
        <p role="alert" className="mt-2 text-xs text-danger">
          {error}
        </p>
      )}
    </fieldset>
  );
}
