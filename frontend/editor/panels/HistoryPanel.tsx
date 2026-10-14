"use client";

import { ExternalLink, FileDiff, Loader2, RotateCcw } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useDocumentEditor } from "@/editor/EditorState";
import { useI18n } from "@/i18n/I18nProvider";
import { formatDateTime, formatRelative } from "@/i18n/format";
import { format } from "@/i18n/locales";
import { errorMessage, restoreVersion } from "@/services/api";
import { useVersions } from "@/services/queries";
import type { DocumentVersion } from "@/types/document";

/**
 * The History rail panel (корекции.docx §31): every kept version -- the
 * original, then the latest changes -- what each did, who and when. Any of them
 * can be compared with the document now (opens beside the editor) or restored,
 * which is saved as a new change and can itself be undone.
 */
export function HistoryPanel() {
  const { document, change } = useDocumentEditor();
  const { m, locale } = useI18n();
  const t = m.edPanels.history;
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
      setRestoreError(errorMessage(err, t.restoreFailed));
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
        {t.beforeAfter}
        <span className="sr-only">{m.edPanels.common.newTab}</span>
      </a>
      <p className="text-xs text-muted">{t.intro}</p>

      {isPending && (
        <p className="flex items-center gap-2 text-sm text-muted">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {m.edPanels.common.loading}
        </p>
      )}
      {error && <p className="text-sm text-danger">{errorMessage(error)}</p>}

      <ol className="flex flex-col divide-y divide-line">
        {(versions ?? []).map((version) => (
          <li key={version.number} className="py-2.5">
            <div className="flex items-start justify-between gap-2">
              <span className="min-w-0">
                <span className="block text-sm font-medium text-foreground">
                  {version.description}
                  {version.current && <span className="ml-1.5 rounded-full bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">{t.now}</span>}
                  {version.kind === "created" && <span className="ml-1.5 rounded-full bg-surface-muted px-1.5 py-0.5 text-[10px] font-medium text-muted">{t.original}</span>}
                </span>
                <span className="block text-xs text-muted" title={formatDateTime(version.createdAt, locale)}>
                  {format(t.version, { number: version.number, when: formatRelative(version.createdAt, locale) })}
                  {version.author && ` · ${version.author}`}
                </span>
              </span>
            </div>
            {!version.current && (
              <div className="mt-1.5 flex gap-3 text-xs">
                <a href={compareLink(version.number)} target="_blank" rel="noopener" className="flex items-center gap-1 font-medium text-accent hover:underline">
                  <ExternalLink className="h-3 w-3" aria-hidden="true" /> {t.compare}
                </a>
                <button
                  type="button"
                  onClick={() => {
                    setRestoreError(null);
                    setRestoring(version);
                  }}
                  className="flex items-center gap-1 font-medium text-muted hover:text-accent"
                >
                  <RotateCcw className="h-3 w-3" aria-hidden="true" /> {t.restore}
                </button>
              </div>
            )}
          </li>
        ))}
      </ol>

      {restoring && (
        <ConfirmDialog
          title={format(t.restoreTitle, { number: restoring.number })}
          confirmLabel={t.restore}
          busy={busy}
          error={restoreError}
          onConfirm={() => void restore()}
          onCancel={() => setRestoring(null)}
        >
          <p>{format(t.restoreBody, { description: restoring.description })}</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
