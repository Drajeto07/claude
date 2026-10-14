"use client";

import { AlertTriangle, CheckCircle2, Loader2, MessageCircleQuestion, MinusCircle, Wrench, XCircle } from "lucide-react";
import { useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { ProposalsList } from "@/editor/panels/ProposalsList";
import { selectElementById } from "@/editor/useSelection";
import { useI18n } from "@/i18n/I18nProvider";
import { format, plural } from "@/i18n/locales";
import { errorMessage, explainHealth, proposeHealthFixes } from "@/services/api";
import { useAccessibility, useHealth } from "@/services/queries";
import type { HealthCheck, HealthReport } from "@/types/document";

const ORDER: Record<HealthCheck["status"], number> = { fail: 0, warn: 1, pass: 2, skip: 3 };
const RATING: Record<HealthReport["rating"], string> = {
  good: "bg-success/10 text-success ring-success/30",
  fair: "bg-warning-soft text-warning ring-warning/30",
  poor: "bg-danger/10 text-danger ring-danger/30",
};

function StatusIcon({ status }: { status: HealthCheck["status"] }) {
  const label = useI18n().m.edPanels.health.status[status];
  const common = "mt-0.5 h-4 w-4 shrink-0";
  if (status === "pass") return <CheckCircle2 className={`${common} text-success`} aria-label={label} />;
  if (status === "warn") return <AlertTriangle className={`${common} text-warning`} aria-label={label} />;
  if (status === "fail") return <XCircle className={`${common} text-danger`} aria-label={label} />;
  return <MinusCircle className={`${common} text-muted`} aria-label={label} />;
}

/**
 * The Health rail panel (корекции.docx §38): Document Health. The score comes
 * from deterministic checks of the saved document only, never from an AI; each
 * issue can show its elements in the editor. What can be put right deterministically
 * is offered as fixes (HLTH-002): proposed, shown with what they change, and applied
 * only when accepted.
 */
/** Checks with their issues, each issue able to show its blocks; worst first. */
function CheckList({ checks, onShow, fixes }: { checks: HealthCheck[]; onShow: (elementId: string) => void; fixes?: (check: HealthCheck) => React.ReactNode }) {
  const show = useI18n().m.edPanels.common.show;
  return (
    <ul className="flex flex-col gap-3">
      {[...checks].sort((a, b) => ORDER[a.status] - ORDER[b.status]).map((check) => (
        <li key={check.id}>
          <div className="flex items-start gap-2">
            <StatusIcon status={check.status} />
            <span className="min-w-0">
              {/* A check that doesn't apply is quieter, but still readable (no opacity: FEAT-011). */}
              <span className={`block text-sm font-medium ${check.status === "skip" ? "text-muted" : "text-foreground"}`}>{check.title}</span>
              <span className="block text-xs text-muted">{check.summary}</span>
            </span>
          </div>
          {check.status !== "pass" && check.issues.length > 0 && (
            <ul className="mt-1.5 ml-6 flex flex-col gap-1">
              {check.issues.map((issue) => (
                <li key={issue.message} className="text-xs text-muted">
                  {issue.message}
                  {issue.elementIds.length > 0 && (
                    <span className="ml-1.5 inline-flex flex-wrap gap-1">
                      {issue.elementIds.slice(0, 5).map((elementId, index) => (
                        <button key={elementId} type="button" onClick={() => onShow(elementId)} className="font-medium text-accent hover:underline">
                          {issue.elementIds.length === 1 ? show : `#${index + 1}`}
                        </button>
                      ))}
                      {issue.elementIds.length > 5 && <span>+{issue.elementIds.length - 5}</span>}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {fixes?.(check)}
        </li>
      ))}
    </ul>
  );
}

/** The accessibility checker (brief §97, FEAT-010): can the document be read with a screen reader
 * and by people who see less well. No score: each check says what it found. */
function AccessibilitySection({ onShow }: { onShow: (elementId: string) => void }) {
  const { document } = useDocumentEditor();
  const { data: report, error } = useAccessibility(document.id, document.revision);
  const { m } = useI18n();
  const t = m.edPanels.health;
  return (
    <section aria-label={t.accessibility} className="flex flex-col gap-3 border-t border-line pt-4">
      <div>
        <h3 className="text-sm font-semibold text-foreground">{t.accessibility}</h3>
        <p className="text-xs text-muted">
          {report ? (report.problems === 0 ? t.accessibleOk : plural(report.problems, t.toLook)) : m.edPanels.common.checking}
        </p>
      </div>
      {error && <p className="text-sm text-danger">{errorMessage(error)}</p>}
      {report && <CheckList checks={report.checks} onShow={onShow} />}
    </section>
  );
}

export function HealthPanel() {
  const { document, editor, change } = useDocumentEditor();
  const { data: report, isPending, isFetching, error } = useHealth(document.id, document.revision);
  const { m } = useI18n();
  const t = m.edPanels.health;
  const common = m.edPanels.common;
  const [proposing, setProposing] = useState<string | null>(null);
  const [fixError, setFixError] = useState<string | null>(null);
  // The AI's explanation of each check, as asked for (HLTH-003): text, or why there is none.
  const [explained, setExplained] = useState<Record<string, string>>({});
  const [explaining, setExplaining] = useState<string | null>(null);

  async function explain(check: HealthCheck) {
    setExplaining(check.id);
    try {
      const answer = await explainHealth(document.id, [check.id]);
      const found = answer.explanations.find((item) => item.checkId === check.id)?.explanation;
      setExplained((current) => ({
        ...current,
        [check.id]: found ?? (answer.available ? t.noExplanation : t.unavailable),
      }));
    } catch (err) {
      setExplained((current) => ({ ...current, [check.id]: errorMessage(err, t.explainFailed) }));
    } finally {
      setExplaining(null);
    }
  }

  async function proposeFixes(checkIds: string[] | undefined, key: string) {
    setProposing(key);
    setFixError(null);
    try {
      await change(async (documentId) => (await proposeHealthFixes(documentId, checkIds)).document);
    } catch (err) {
      setFixError(errorMessage(err, common.fixesFailed));
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
      <p className="flex items-center gap-2 text-sm text-muted">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {common.checking}
      </p>
    );
  }
  if (error) return <p className="text-sm text-danger">{errorMessage(error)}</p>;

  const rating = { label: t.ratings[report.rating], className: RATING[report.rating] };
  const fixable = report.checks.reduce((total, check) => total + check.fixes, 0);

  return (
    <div className="flex flex-col gap-4">
      <div className={`flex items-center gap-4 rounded-lg p-3 ring-1 ${rating.className}`}>
        <span className="text-3xl font-semibold tabular-nums">{report.score}</span>
        <span>
          <span className="block text-sm font-semibold">{rating.label}</span>
          <span className="block text-xs">{format(t.from, { count: report.checks.filter((check) => check.status !== "skip").length })}</span>
        </span>
        {isFetching && <Loader2 className="ml-auto h-4 w-4 animate-spin opacity-60" aria-label={t.checkingAgain} />}
      </div>

      <ProposalsList source="health" />
      {fixable > 0 && (
        <button
          type="button"
          onClick={() => void proposeFixes(undefined, "all")}
          disabled={proposing !== null}
          className="flex items-center justify-center gap-1.5 rounded-full border border-line-strong px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface-muted disabled:opacity-50"
        >
          <Wrench className="h-3.5 w-3.5" aria-hidden="true" />
          {plural(fixable, t.proposeAll)}
        </button>
      )}
      {fixError && <p className="text-sm text-danger">{fixError}</p>}

      <CheckList
        checks={report.checks}
        onShow={show}
        fixes={(check) => (
          <>
            {check.fixes > 0 && (
              <button
                type="button"
                onClick={() => void proposeFixes([check.id], check.id)}
                disabled={proposing !== null}
                aria-label={format(t.proposeFor, { title: check.title })}
                className="mt-1.5 ml-6 flex items-center gap-1 text-xs font-medium text-accent hover:underline disabled:opacity-50"
              >
                <Wrench className="h-3.5 w-3.5" aria-hidden="true" />
                {proposing === check.id ? common.workingOut : plural(check.fixes, common.proposeFixes)}
              </button>
            )}
            {(check.status === "warn" || check.status === "fail") &&
              (explained[check.id] ? (
                <p className="mt-1.5 ml-6 rounded bg-surface-muted p-2 text-xs text-foreground" aria-label={format(t.explanation, { title: check.title })}>
                  {explained[check.id]}
                </p>
              ) : (
                <button
                  type="button"
                  onClick={() => void explain(check)}
                  disabled={explaining !== null}
                  aria-label={format(t.explainFor, { title: check.title })}
                  className="mt-1.5 ml-6 flex items-center gap-1 text-xs font-medium text-muted hover:underline disabled:opacity-50"
                >
                  <MessageCircleQuestion className="h-3.5 w-3.5" aria-hidden="true" />
                  {explaining === check.id ? t.explaining : t.explain}
                </button>
              ))}
          </>
        )}
      />
      <AccessibilitySection onShow={show} />
      <p className="text-xs text-muted">{t.footnote}</p>
    </div>
  );
}
