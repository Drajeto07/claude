"use client";

import { AlertTriangle, CheckCircle2, Loader2, MinusCircle, Wrench, XCircle } from "lucide-react";
import { useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { ProposalsList } from "@/editor/panels/ProposalsList";
import { selectElementById } from "@/editor/useSelection";
import { errorMessage, proposeHealthFixes } from "@/services/api";
import { useHealth } from "@/services/queries";
import type { HealthCheck, HealthReport } from "@/types/document";

const ORDER: Record<HealthCheck["status"], number> = { fail: 0, warn: 1, pass: 2, skip: 3 };
const RATING: Record<HealthReport["rating"], { label: string; className: string }> = {
  good: { label: "Good", className: "bg-green-50 text-green-800 ring-green-600/20 dark:bg-green-950/40 dark:text-green-300" },
  fair: { label: "Fair", className: "bg-amber-50 text-amber-800 ring-amber-600/20 dark:bg-amber-950/40 dark:text-amber-300" },
  poor: { label: "Needs work", className: "bg-red-50 text-red-800 ring-red-600/20 dark:bg-red-950/40 dark:text-red-300" },
};

function StatusIcon({ status }: { status: HealthCheck["status"] }) {
  const common = "mt-0.5 h-4 w-4 shrink-0";
  if (status === "pass") return <CheckCircle2 className={`${common} text-green-600`} aria-label="Fine" />;
  if (status === "warn") return <AlertTriangle className={`${common} text-amber-500`} aria-label="Worth a look" />;
  if (status === "fail") return <XCircle className={`${common} text-red-600`} aria-label="Problem" />;
  return <MinusCircle className={`${common} text-zinc-300 dark:text-zinc-600`} aria-label="Doesn't apply" />;
}

/**
 * The "Здраве" rail panel (корекции.docx §38): Document Health. The score comes
 * from deterministic checks of the saved document only, never from an AI; each
 * issue can show its elements in the editor. What can be put right deterministically
 * is offered as fixes (HLTH-002): proposed, shown with what they change, and applied
 * only when accepted.
 */
export function HealthPanel() {
  const { document, editor, change } = useDocumentEditor();
  const { data: report, isPending, isFetching, error } = useHealth(document.id, document.revision);
  const [proposing, setProposing] = useState<string | null>(null);
  const [fixError, setFixError] = useState<string | null>(null);

  async function proposeFixes(checkIds: string[] | undefined, key: string) {
    setProposing(key);
    setFixError(null);
    try {
      await change(async (documentId) => (await proposeHealthFixes(documentId, checkIds)).document);
    } catch (err) {
      setFixError(errorMessage(err, "Couldn't work out the fixes."));
    } finally {
      setProposing(null);
    }
  }

  function show(elementId: string) {
    if (!editor || editor.isDestroyed) return;
    selectElementById(editor, elementId);
    editor.view.dom.querySelector(`[data-element-id="${CSS.escape(elementId)}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  if (isPending) {
    return (
      <p className="flex items-center gap-2 text-sm text-zinc-500">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Checking…
      </p>
    );
  }
  if (error) return <p className="text-sm text-red-600 dark:text-red-400">{errorMessage(error)}</p>;

  const checks = [...report.checks].sort((a, b) => ORDER[a.status] - ORDER[b.status]);
  const rating = RATING[report.rating];
  const fixable = report.checks.reduce((total, check) => total + check.fixes, 0);

  return (
    <div className="flex flex-col gap-4">
      <div className={`flex items-center gap-4 rounded-lg p-3 ring-1 ${rating.className}`}>
        <span className="text-3xl font-semibold tabular-nums">{report.score}</span>
        <span>
          <span className="block text-sm font-semibold">{rating.label}</span>
          <span className="block text-xs opacity-80">From {report.checks.filter((check) => check.status !== "skip").length} checks of the saved document</span>
        </span>
        {isFetching && <Loader2 className="ml-auto h-4 w-4 animate-spin opacity-60" aria-label="Checking again" />}
      </div>

      <ProposalsList source="health" />
      {fixable > 0 && (
        <button
          type="button"
          onClick={() => void proposeFixes(undefined, "all")}
          disabled={proposing !== null}
          className="flex items-center justify-center gap-1.5 rounded-full border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          <Wrench className="h-3.5 w-3.5" aria-hidden="true" />
          Propose all {fixable} fix{fixable === 1 ? "" : "es"}
        </button>
      )}
      {fixError && <p className="text-sm text-red-600 dark:text-red-400">{fixError}</p>}

      <ul className="flex flex-col gap-3">
        {checks.map((check) => (
          <li key={check.id} className={check.status === "skip" ? "opacity-60" : undefined}>
            <div className="flex items-start gap-2">
              <StatusIcon status={check.status} />
              <span className="min-w-0">
                <span className="block text-sm font-medium text-zinc-800 dark:text-zinc-200">{check.title}</span>
                <span className="block text-xs text-zinc-500 dark:text-zinc-400">{check.summary}</span>
              </span>
            </div>
            {check.status !== "pass" && check.issues.length > 0 && (
              <ul className="mt-1.5 ml-6 flex flex-col gap-1">
                {check.issues.map((issue) => (
                  <li key={issue.message} className="text-xs text-zinc-600 dark:text-zinc-400">
                    {issue.message}
                    {issue.elementIds.length > 0 && (
                      <span className="ml-1.5 inline-flex flex-wrap gap-1">
                        {issue.elementIds.slice(0, 5).map((elementId, index) => (
                          <button key={elementId} type="button" onClick={() => show(elementId)} className="font-medium text-accent hover:underline">
                            {issue.elementIds.length === 1 ? "Show" : `#${index + 1}`}
                          </button>
                        ))}
                        {issue.elementIds.length > 5 && <span>+{issue.elementIds.length - 5}</span>}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {check.fixes > 0 && (
              <button
                type="button"
                onClick={() => void proposeFixes([check.id], check.id)}
                disabled={proposing !== null}
                aria-label={`Propose fixes: ${check.title}`}
                className="mt-1.5 ml-6 flex items-center gap-1 text-xs font-medium text-accent hover:underline disabled:opacity-50"
              >
                <Wrench className="h-3.5 w-3.5" aria-hidden="true" />
                {proposing === check.id ? "Working them out…" : `Propose ${check.fixes} fix${check.fixes === 1 ? "" : "es"}`}
              </button>
            )}
          </li>
        ))}
      </ul>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">Links are checked as written, not visited. Typing counts once it is saved. Fixes are worked out by rules, never by an AI.</p>
    </div>
  );
}
