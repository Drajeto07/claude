"use client";

import { ExternalLink, FileDiff, Loader2, RotateCcw } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useDocumentEditor } from "@/editor/EditorState";
import { formatDateTime, formatWhen } from "@/lib/format";
import { errorMessage, restoreVersion } from "@/services/api";
import { useVersions } from "@/services/queries";
import type { DocumentVersion } from "@/types/document";

/**
 * The "История" rail panel (корекции.docx §31): every kept version -- the
 * original, then the latest changes -- what each did, who and when. Any of them
 * can be compared with the document now (opens beside the editor) or restored,
 * which is saved as a new change and can itself be undone.
 */
export function HistoryPanel() {
  const { document, change } = useDocumentEditor();
  const { data: versions, isPending, error } = useVersions(document.id, document.revision);
  const [restoring, setRestoring] = useState<DocumentVersion | null>(null);
  const [busy, setBusy] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);

  async function restore() {
    if (!restoring) return;
    setBusy(true);
    setRestoreError(null);
    try {
      await change((documentId) => restoreVersion(documentId, restoring.number));
      setRestoring(null);
    } catch (err) {
      setRestoreError(errorMessage(err, "That version couldn't be restored."));
    } finally {
      setBusy(false);
    }
  }

  const compareLink = (from?: number) => `/documents/${document.id}/compare${from ? `?from=${from}` : ""}`;

  return (
    <div className="flex flex-col gap-3">
      <a
        href={compareLink()}
        target="_blank"
        rel="noopener"
        className="flex items-center justify-center gap-1.5 rounded-full border border-accent px-4 py-2 text-sm font-medium text-accent hover:bg-accent/5"
      >
        <FileDiff className="h-4 w-4" aria-hidden="true" />
        Before and after
        <span className="sr-only">(opens in a new tab)</span>
      </a>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">The original, then the latest changes. Typing saved within a minute counts as one change.</p>

      {isPending && (
        <p className="flex items-center gap-2 text-sm text-zinc-500">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading…
        </p>
      )}
      {error && <p className="text-sm text-red-600 dark:text-red-400">{errorMessage(error)}</p>}

      <ol className="flex flex-col divide-y divide-zinc-100 dark:divide-zinc-800">
        {(versions ?? []).map((version) => (
          <li key={version.number} className="py-2.5">
            <div className="flex items-start justify-between gap-2">
              <span className="min-w-0">
                <span className="block text-sm font-medium text-zinc-800 dark:text-zinc-200">
                  {version.description}
                  {version.current && <span className="ml-1.5 rounded-full bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">now</span>}
                  {version.kind === "created" && <span className="ml-1.5 rounded-full bg-zinc-100 px-1.5 py-0.5 text-[10px] font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">original</span>}
                </span>
                <span className="block text-xs text-zinc-500 dark:text-zinc-400" title={formatDateTime(version.createdAt)}>
                  Version {version.number} · {formatWhen(version.createdAt)}
                  {version.author && ` · ${version.author}`}
                </span>
              </span>
            </div>
            {!version.current && (
              <div className="mt-1.5 flex gap-3 text-xs">
                <a href={compareLink(version.number)} target="_blank" rel="noopener" className="flex items-center gap-1 font-medium text-accent hover:underline">
                  <ExternalLink className="h-3 w-3" aria-hidden="true" /> Compare with now
                </a>
                <button
                  type="button"
                  onClick={() => {
                    setRestoreError(null);
                    setRestoring(version);
                  }}
                  className="flex items-center gap-1 font-medium text-zinc-600 hover:text-accent dark:text-zinc-400"
                >
                  <RotateCcw className="h-3 w-3" aria-hidden="true" /> Restore
                </button>
              </div>
            )}
          </li>
        ))}
      </ol>

      {restoring && (
        <ConfirmDialog
          title={`Restore version ${restoring.number}?`}
          confirmLabel="Restore"
          busy={busy}
          error={restoreError}
          onConfirm={() => void restore()}
          onCancel={() => setRestoring(null)}
        >
          <p>
            The document goes back to how it was after &ldquo;{restoring.description}&rdquo;. This is saved as a new change, so you can undo it
            afterwards.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
