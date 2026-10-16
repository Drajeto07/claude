"use client";

import { Eraser } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { createCleanCopy, errorMessage } from "@/services/api";
import type { CleanCopyOptions, CleanCopyResponse } from "@/types/document";

const ACTIONS: { key: keyof CleanCopyOptions; label: string }[] = [
  { key: "removeComments", label: "Remove comments" },
  { key: "acceptTrackedChanges", label: "Accept tracked changes" },
  { key: "removeHiddenText", label: "Remove hidden text" },
  { key: "removeMetadata", label: "Remove the file's metadata (author, dates, keywords…)" },
  { key: "normaliseFormatting", label: "Normalise formatting (fonts, sizes and colours set apart from the styles)" },
];

/**
 * Clean copy (brief §59, tracker REV-005): a new document with what the person ticks taken out --
 * nothing is ticked to begin with, each action is theirs to choose. This document stays as it is.
 */
export function CleanCopySection() {
  const { document, flush } = useDocumentEditor();
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
  const any = ACTIONS.some((action) => chosen[action.key]);

  async function create() {
    setBusy(true);
    setError(null);
    setMade(null);
    try {
      await flush(); // the copy is of what is saved: typing waiting to be saved goes first
      setMade(await createCleanCopy(document.id, chosen));
    } catch (err) {
      setError(errorMessage(err, "Couldn't make the clean copy."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Clean copy" className="flex flex-col gap-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">Clean copy</h3>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">A new document with what you tick taken out. This one stays as it is.</p>
      <fieldset disabled={busy} className="flex flex-col gap-1">
        {ACTIONS.map((action) => (
          <label key={action.key} className="flex items-start gap-2 text-xs text-zinc-700 dark:text-zinc-300">
            <input
              type="checkbox"
              checked={Boolean(chosen[action.key])}
              onChange={(event) => setChosen((current) => ({ ...current, [action.key]: event.target.checked }))}
              className="mt-0.5 h-3.5 w-3.5 rounded border-zinc-300 text-accent focus:ring-accent dark:border-zinc-700"
            />
            {action.label}
          </label>
        ))}
      </fieldset>
      {keepsTrackedChanges && !chosen.acceptTrackedChanges && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">This document keeps tracked changes for Word: a clean copy can only have them accepted.</p>
      )}
      <button
        type="button"
        onClick={() => void create()}
        disabled={!any || busy}
        className="flex items-center justify-center gap-1.5 self-start rounded-full border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
      >
        <Eraser className="h-3.5 w-3.5" aria-hidden="true" />
        {busy ? "Making the copy…" : "Create clean copy"}
      </button>
      {error && (
        <p role="alert" className="text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
      {made && (
        <div role="status" className="text-xs text-zinc-700 dark:text-zinc-300">
          <p>{summarise(made.summary)}</p>
          {made.summary.originalFileLeftOut && <p className="text-zinc-500">It has no original Word file behind it: its Word export is written from the document alone.</p>}
          <Link href={`/documents/${made.document.id}`} className="font-medium text-accent hover:underline">
            Open “{made.document.metadata.title}”
          </Link>
        </div>
      )}
    </section>
  );
}

function summarise(summary: CleanCopyResponse["summary"]): string {
  const done = [
    summary.commentsRemoved ? `${summary.commentsRemoved} comment${summary.commentsRemoved === 1 ? "" : "s"} removed` : null,
    summary.trackedChangesAccepted ? "tracked changes accepted" : null,
    summary.hiddenRunsRemoved ? `hidden text removed in ${summary.hiddenRunsRemoved} place${summary.hiddenRunsRemoved === 1 ? "" : "s"}` : null,
    summary.metadataRemoved?.length ? `metadata removed (${summary.metadataRemoved.join(", ")})` : null,
    summary.formattingRemoved ? `${summary.formattingRemoved} formatting override${summary.formattingRemoved === 1 ? "" : "s"} removed` : null,
  ].filter(Boolean);
  return done.length ? `Made: ${done.join("; ")}.` : "Made: there was nothing of what you chose to take out.";
}
