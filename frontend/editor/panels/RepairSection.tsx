"use client";

import { Wrench } from "lucide-react";
import { useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { useI18n } from "@/i18n/I18nProvider";
import { format, plural } from "@/i18n/locales";
import { errorMessage, proposeHealthFixes } from "@/services/api";
import { useRepair } from "@/services/queries";

/**
 * Repair document (brief §60, tracker REV-004): what is broken, by kind, each with its fixes.
 * Detected issue, proposed fix, preview, apply: a fix is proposed below as a change to review --
 * shown with the block as it would be -- and only accepting it applies it. The findings are
 * Document Health's checks; nothing is worked out by an AI.
 */
export function RepairSection({ onShow }: { onShow: (elementId: string) => void }) {
  const { document, change } = useDocumentEditor();
  const { m } = useI18n();
  const t = m.edPanels.repair;
  const common = m.edPanels.common;
  const { data: report } = useRepair(document.id, document.revision);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!report || report.issues.length === 0) return null;

  async function propose(checkIds: string[], key: string) {
    setBusy(key);
    setError(null);
    try {
      await change(async (documentId) => (await proposeHealthFixes(documentId, checkIds)).document);
    } catch (err) {
      setError(errorMessage(err, common.fixesFailed));
    } finally {
      setBusy(null);
    }
  }

  const fixable = report.issues.filter((issue) => issue.fixes > 0);
  return (
    <section aria-label={t.title} className="flex flex-col gap-2 rounded-lg border border-line p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-foreground">{t.title}</h3>
          <p className="text-xs text-muted">{t.intro}</p>
        </div>
        {report.fixes > 1 && (
          <button
            type="button"
            onClick={() => void propose(fixable.map((issue) => issue.checkId), "all")}
            disabled={busy !== null}
            className="flex shrink-0 items-center gap-1 rounded-full border border-line-strong px-2.5 py-1 text-xs font-medium text-foreground hover:bg-surface-muted disabled:opacity-50"
          >
            <Wrench className="h-3.5 w-3.5" aria-hidden="true" />
            {format(t.proposeAll, { count: report.fixes })}
          </button>
        )}
      </div>
      <ul className="flex flex-col gap-2">
        {report.issues.map((issue) => (
          <li key={issue.checkId} className="text-xs text-foreground">
            <p>
              <span className={issue.status === "fail" ? "font-semibold text-danger" : "font-semibold text-warning"}>
                {t.kinds[issue.kind]}
              </span>
              {" · "}
              {issue.title}: {issue.summary}
            </p>
            <div className="mt-0.5 flex flex-wrap items-center gap-2">
              {issue.elementIds.slice(0, 3).map((elementId, index) => (
                <button key={elementId} type="button" onClick={() => onShow(elementId)} className="text-accent hover:underline">
                  {issue.elementIds.length > 1 ? format(common.showNumbered, { number: index + 1 }) : common.show}
                </button>
              ))}
              {issue.fixes > 0 ? (
                <button
                  type="button"
                  aria-label={format(t.proposeFor, { title: issue.title })}
                  onClick={() => void propose([issue.checkId], issue.checkId)}
                  disabled={busy !== null}
                  className="font-medium text-accent hover:underline disabled:opacity-50"
                >
                  {busy === issue.checkId ? common.workingOut : plural(issue.fixes, common.proposeFixes)}
                </button>
              ) : (
                <span className="text-muted">{t.noFix}</span>
              )}
            </div>
          </li>
        ))}
      </ul>
      {error && <p className="text-xs text-danger">{error}</p>}
    </section>
  );
}
