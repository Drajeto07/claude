"use client";

import { Wrench } from "lucide-react";
import { useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { errorMessage, proposeHealthFixes } from "@/services/api";
import { useRepair } from "@/services/queries";
import type { RepairIssue } from "@/types/document";

const KINDS: Record<RepairIssue["kind"], string> = {
  numbering: "Numbering and headings",
  styles: "Inconsistent styles",
  tables: "Tables",
  links: "Links",
  structures: "What the app doesn't hold",
  input: "Malformed input",
};

/**
 * Repair document (brief §60, tracker REV-004): what is broken, by kind, each with its fixes.
 * Detected issue, proposed fix, preview, apply: a fix is proposed below as a change to review --
 * shown with the block as it would be -- and only accepting it applies it. The findings are
 * Document Health's checks; nothing is worked out by an AI.
 */
export function RepairSection({ onShow }: { onShow: (elementId: string) => void }) {
  const { document, change } = useDocumentEditor();
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
      setError(errorMessage(err, "Couldn't work out the fixes."));
    } finally {
      setBusy(null);
    }
  }

  const fixable = report.issues.filter((issue) => issue.fixes > 0);
  return (
    <section aria-label="Repair document" className="flex flex-col gap-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">Repair document</h3>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">Fixes are proposed below for you to review; nothing changes until you accept.</p>
        </div>
        {report.fixes > 1 && (
          <button
            type="button"
            onClick={() => void propose(fixable.map((issue) => issue.checkId), "all")}
            disabled={busy !== null}
            className="flex shrink-0 items-center gap-1 rounded-full border border-zinc-300 px-2.5 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            <Wrench className="h-3.5 w-3.5" aria-hidden="true" />
            Propose all {report.fixes} repairs
          </button>
        )}
      </div>
      <ul className="flex flex-col gap-2">
        {report.issues.map((issue) => (
          <li key={issue.checkId} className="text-xs text-zinc-700 dark:text-zinc-300">
            <p>
              <span className={issue.status === "fail" ? "font-semibold text-red-700 dark:text-red-400" : "font-semibold text-amber-700 dark:text-amber-400"}>
                {KINDS[issue.kind]}
              </span>
              {" · "}
              {issue.title}: {issue.summary}
            </p>
            <div className="mt-0.5 flex flex-wrap items-center gap-2">
              {issue.elementIds.slice(0, 3).map((elementId, index) => (
                <button key={elementId} type="button" onClick={() => onShow(elementId)} className="text-accent hover:underline">
                  Show{issue.elementIds.length > 1 ? ` ${index + 1}` : ""}
                </button>
              ))}
              {issue.fixes > 0 ? (
                <button
                  type="button"
                  aria-label={`Propose repairs: ${issue.title}`}
                  onClick={() => void propose([issue.checkId], issue.checkId)}
                  disabled={busy !== null}
                  className="font-medium text-accent hover:underline disabled:opacity-50"
                >
                  {busy === issue.checkId ? "Working them out…" : `Propose ${issue.fixes} fix${issue.fixes === 1 ? "" : "es"}`}
                </button>
              ) : (
                <span className="text-zinc-500">No fix can be worked out: check it yourself.</span>
              )}
            </div>
          </li>
        ))}
      </ul>
      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
    </section>
  );
}
