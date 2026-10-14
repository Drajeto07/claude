"use client";

import { Eraser } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { useI18n } from "@/i18n/I18nProvider";
import { format, plural } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages/en";
import { createCleanCopy, errorMessage } from "@/services/api";
import type { CleanCopyOptions, CleanCopyResponse } from "@/types/document";

const ACTIONS: (keyof CleanCopyOptions)[] = ["removeComments", "acceptTrackedChanges", "removeHiddenText", "removeMetadata", "normaliseFormatting"];

type Words = Messages["edPanels"]["clean"];

/**
 * Clean copy (brief §59, tracker REV-005): a new document with what the person ticks taken out --
 * nothing is ticked to begin with, each action is theirs to choose. This document stays as it is.
 */
export function CleanCopySection() {
  const { document, flush } = useDocumentEditor();
  const t = useI18n().m.edPanels.clean;
  // Nothing chosen to begin with: each action is the person's (brief §59).
  const [chosen, setChosen] = useState<CleanCopyOptions>({
    removeComments: false,
    acceptTrackedChanges: false,
    removeHiddenText: false,
    removeMetadata: false,
    normaliseFormatting: false,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [made, setMade] = useState<CleanCopyResponse | null>(null);
  const keepsTrackedChanges = document.trackedChanges === "kept";
  const any = ACTIONS.some((action) => chosen[action]);

  async function create() {
    setBusy(true);
    setError(null);
    setMade(null);
    try {
      await flush(); // the copy is of what is saved: typing waiting to be saved goes first
      setMade(await createCleanCopy(document.id, chosen));
    } catch (err) {
      setError(errorMessage(err, t.failed));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label={t.title} className="flex flex-col gap-2 rounded-lg border border-line p-3">
      <h3 className="text-sm font-semibold text-foreground">{t.title}</h3>
      <p className="text-xs text-muted">{t.intro}</p>
      <fieldset disabled={busy} className="flex flex-col gap-1">
        {ACTIONS.map((action) => (
          <label key={action} className="flex items-start gap-2 text-xs text-foreground">
            <input
              type="checkbox"
              checked={Boolean(chosen[action])}
              onChange={(event) => setChosen((current) => ({ ...current, [action]: event.target.checked }))}
              className="mt-0.5 h-3.5 w-3.5 rounded border-line-strong text-accent focus:ring-accent"
            />
            {t.actions[action]}
          </label>
        ))}
      </fieldset>
      {keepsTrackedChanges && !chosen.acceptTrackedChanges && (
        <p className="text-xs text-muted">{t.keepsTracked}</p>
      )}
      <button
        type="button"
        onClick={() => void create()}
        disabled={!any || busy}
        className="flex items-center justify-center gap-1.5 self-start rounded-full border border-line-strong px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface-muted disabled:opacity-50"
      >
        <Eraser className="h-3.5 w-3.5" aria-hidden="true" />
        {busy ? t.making : t.create}
      </button>
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
      {made && (
        <div role="status" className="text-xs text-foreground">
          <p>{summarise(made.summary, t)}</p>
          {made.summary.originalFileLeftOut && <p className="text-muted">{t.noOriginal}</p>}
          <Link href={`/documents/${made.document.id}`} className="font-medium text-accent hover:underline">
            {format(t.open, { title: made.document.metadata.title })}
          </Link>
        </div>
      )}
    </section>
  );
}

function summarise(summary: CleanCopyResponse["summary"], t: Words): string {
  const done = [
    summary.commentsRemoved ? plural(summary.commentsRemoved, t.comments) : null,
    summary.trackedChangesAccepted ? t.tracked : null,
    summary.hiddenRunsRemoved ? plural(summary.hiddenRunsRemoved, t.hidden) : null,
    summary.metadataRemoved?.length ? format(t.metadata, { list: summary.metadataRemoved.join(", ") }) : null,
    summary.formattingRemoved ? plural(summary.formattingRemoved, t.overrides) : null,
  ].filter(Boolean);
  return done.length ? format(t.made, { list: done.join("; ") }) : t.madeNothing;
}
