"use client";

import { AlertTriangle, Archive, CheckCircle2, CircleSlash, HelpCircle, MinusCircle, ShieldCheck, XCircle } from "lucide-react";

import { TrackedChangesChoice } from "@/components/TrackedChangesChoice";
import { CleanCopySection } from "@/editor/panels/CleanCopySection";
import { useDocumentEditor } from "@/editor/EditorState";
import { selectElementById } from "@/editor/useSelection";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import { setTrackedChanges } from "@/services/api";
import type { ContentDifference, FidelityItem, FidelityPolicy, FidelityReport, PdfAspectConfidence, PdfConversion } from "@/types/document";

const POLICY: Record<FidelityPolicy, { icon: typeof AlertTriangle; className: string }> = {
  unsupported: { icon: XCircle, className: "text-danger" },
  blocked: { icon: CircleSlash, className: "text-danger" },
  lossy: { icon: AlertTriangle, className: "text-warning" },
  detected_not_editable: { icon: Archive, className: "text-sky-600 dark:text-sky-400" },
  detected_preserved: { icon: CheckCircle2, className: "text-success" },
  not_detected: { icon: HelpCircle, className: "text-muted" },
};
const ORDER: FidelityPolicy[] = ["unsupported", "blocked", "lossy", "detected_not_editable", "detected_preserved", "not_detected"];


const percent = (value: number) => `${Math.round(value * 100)}%`;

/** "Imported from PDF" with how sure the conversion is, aspect by aspect (brief §88, §93; P2E-005/P2E-007). */
function PdfConversionSummary({ conversion }: { conversion: PdfConversion }) {
  const t = useI18n().m.edPanels.fidelity;
  const mode = conversion.mode === "layout" ? t.layoutMode : t.editableMode;
  const tone = conversion.confidence >= 0.75 ? "text-success" : conversion.confidence >= 0.6 ? "text-warning" : "text-danger";
  return (
    <section aria-label={t.pdfLabel} className="rounded-lg bg-surface-muted p-3 ring-1 ring-line">
      <h3 className="text-sm font-semibold text-foreground">
        {t.importedPdf} <span className="font-normal text-muted">· {conversion.rebuilt ? mode : t.textOnly}</span>
      </h3>
      <p className="mt-0.5 text-xs text-muted">
        {t.confidence} <span className={`font-semibold ${tone}`}>{percent(conversion.confidence)}</span>
        {conversion.lowConfidenceBlocks > 0 &&
          format(t.guesses, { low: conversion.lowConfidenceBlocks, count: conversion.blocks })}
      </p>
      <ul className="mt-2 flex flex-col gap-1">
        {conversion.aspects.map((aspect) => (
          <li key={aspect.aspect} className="text-xs text-muted">
            <span className="font-medium text-foreground">{t.aspects[aspect.aspect as PdfAspectConfidence["aspect"]]}</span> {percent(aspect.confidence)}
            {aspect.note && <span className="block opacity-80">{aspect.note}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The one-line verdict: "No content changes" only when the word comparison proved
 * it and nothing else (a header's text, a picture) was left out. */
export type VerdictWords = { unverified: string; changed: string; partial: string; good: string };
const VERDICT_EN: VerdictWords = { unverified: "Content not verified", changed: "Content differs from the source", partial: "Body text complete, some content left out", good: "No content changes" };

/** The import's content check in one line; `words` in the interface language (English by default). */
export function contentVerdict(report: FidelityReport | null, words: VerdictWords = VERDICT_EN): { tone: "good" | "warn" | "none"; text: string } {
  if (!report || report.contentStatus === "unverified") return { tone: "none", text: words.unverified };
  if (report.contentStatus === "changed") return { tone: "warn", text: words.changed };
  if (report.contentLossCount > 0) return { tone: "warn", text: words.partial };
  return { tone: "good", text: words.good };
}

function Verdict({ report }: { report: FidelityReport | null }) {
  const { m } = useI18n();
  const t = m.edPanels.fidelity;
  const verdict = contentVerdict(report, m.edStatus.verdict);
  const content = report?.content ?? null;
  const tone = {
    good: "bg-success/10 text-success ring-success/30",
    warn: "bg-warning-soft text-warning ring-warning/30",
    none: "bg-surface-muted text-foreground ring-line-strong",
  }[verdict.tone];
  const source = content ? ((t.sources as Record<string, string>)[content.method] ?? t.theSource) : "";
  let detail: string = t.noSource;
  if (content?.verified) detail = format(t.allWords, { count: content.sourceWords.toLocaleString(), source });
  else if (content) {
    const parts = [
      content.missing && format(t.missing, { count: content.missing.toLocaleString() }),
      content.added && format(t.added, { count: content.added.toLocaleString() }),
      content.moved && format(t.moved, { count: content.moved.toLocaleString() }),
    ].filter(Boolean);
    detail = format(t.compared, { source, parts: parts.join(", ") });
  }
  return (
    <div className={`flex items-start gap-3 rounded-lg p-3 ring-1 ${tone}`}>
      {verdict.tone === "good" ? <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" /> : <MinusCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />}
      <span>
        <span className="block text-sm font-semibold">{verdict.text}</span>
        <span className="block text-xs opacity-80">{detail}</span>
      </span>
    </div>
  );
}

function Differences({ samples }: { samples: ContentDifference[] }) {
  const t = useI18n().m.edPanels.fidelity;
  if (samples.length === 0) return null;
  return (
    <section>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">{t.whereDiffer}</h3>
      <ul className="flex flex-col gap-1.5">
        {samples.map((sample, index) => (
          <li key={index} className="text-xs text-muted">
            <span className="font-medium text-foreground">{t.differences[sample.kind]}:</span>{" "}
            {sample.context && <span className="opacity-70">…{sample.context} </span>}
            {sample.source && <del className="text-danger">{sample.source}</del>}
            {sample.source && sample.result && " → "}
            {sample.result && <ins className="text-success no-underline">{sample.result}</ins>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Item({ item, onShow }: { item: FidelityItem; onShow: (id: string) => void }) {
  const { m } = useI18n();
  const t = m.edPanels.fidelity;
  const policy = { ...POLICY[item.policy], label: t.policies[item.policy] };
  const Icon = policy.icon;
  return (
    <li className="flex items-start gap-2">
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${policy.className}`} aria-label={policy.label} />
      <span className="min-w-0 text-xs text-muted">
        <span className="block text-sm text-foreground">
          {item.reason}
          {item.count > 1 && <span className="ml-1 text-xs text-muted">×{item.count}</span>}
        </span>
        <span className="block">
          {policy.label}
          {item.contentChanged && t.content}
        </span>
        {item.sourceState && <span className="block truncate" title={item.sourceState}>{format(t.was, { state: item.sourceState })}</span>}
        {item.newState && <span className="block truncate" title={item.newState}>{format(t.nowState, { state: item.newState })}</span>}
        {item.elementIds.length > 0 && (
          <span className="mt-0.5 flex flex-wrap gap-1">
            {item.elementIds.slice(0, 8).map((id, index) => (
              <button key={id} type="button" onClick={() => onShow(id)} className="rounded bg-surface-muted px-1.5 py-0.5 text-[11px] hover:bg-line">
                {format(m.edPanels.common.showNumbered, { number: index + 1 })}
              </button>
            ))}
          </span>
        )}
      </span>
    </li>
  );
}

/**
 * The Check rail panel (brief §17): the Document Fidelity Report of the
 * import -- whether every word of the source made it into the document (checked,
 * never assumed), and each thing that was changed, left out or only kept for export.
 */
/** What the editor holds that the document can't keep: saving goes on without it. */
function WhileEditing({ notes }: { notes: string[] }) {
  const t = useI18n().m.edPanels.fidelity;
  if (notes.length === 0) return null;
  const policy = POLICY.lossy;
  return (
    <section>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">{t.whileEditing}</h3>
      <ul className="flex flex-col gap-3">
        {notes.map((text) => (
          <li key={text} className="flex items-start gap-2">
            <policy.icon className={`mt-0.5 h-4 w-4 shrink-0 ${policy.className}`} aria-label={t.notKept} />
            <span className="min-w-0 text-sm text-foreground">
              {text}
              <span className="block text-xs text-muted">{t.notSaved}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function FidelityPanel() {
  const { document, editor, notKept, change } = useDocumentEditor();
  const t = useI18n().m.edPanels.fidelity;
  const report = document.importReport;

  function show(elementId: string) {
    if (!editor || editor.isDestroyed) return;
    selectElementById(editor, elementId);
    editor.view.dom.querySelector(`[data-element-id="${CSS.escape(elementId)}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  const items = [...(report?.items ?? [])].sort((a, b) => ORDER.indexOf(a.policy) - ORDER.indexOf(b.policy));
  return (
    <div className="flex flex-col gap-4">
      <Verdict report={report} />
      {document.pdfConversion && <PdfConversionSummary conversion={document.pdfConversion} />}
      {document.trackedChanges && document.sourcePackage && (
        <TrackedChangesChoice choice={document.trackedChanges} onChoose={(choice, discardEdits) => change((id) => setTrackedChanges(id, choice, { discardEdits }))} />
      )}
      {report?.content && !report.content.verified && <Differences samples={report.content.samples} />}
      {items.length > 0 && (
        <section>
          <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
            {report!.reviewCount > 0 ? format(t.toReview, { count: report!.reviewCount }) : t.noted}
          </h3>
          <ul className="flex flex-col gap-3">
            {items.map((item) => (
              <Item key={`${item.feature}:${item.reason}`} item={item} onShow={show} />
            ))}
          </ul>
        </section>
      )}
      {report && items.length === 0 && report.content?.verified && <p className="text-xs text-muted">{t.nothing}</p>}
      <WhileEditing notes={notKept} />
      <CleanCopySection />
    </div>
  );
}
