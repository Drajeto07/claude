"use client";

import { AlertTriangle, Archive, CheckCircle2, CircleSlash, HelpCircle, MinusCircle, ShieldCheck, XCircle } from "lucide-react";

import { TrackedChangesChoice } from "@/components/TrackedChangesChoice";
import { useDocumentEditor } from "@/editor/EditorState";
import { selectElementById } from "@/editor/useSelection";
import { setTrackedChanges } from "@/services/api";
import type { ContentDifference, FidelityItem, FidelityPolicy, FidelityReport, PdfAspectConfidence, PdfConversion } from "@/types/document";

/** What was compared with what, for "every word of … is in the document". */
const SOURCE_LABEL: Record<string, string> = {
  "docx-text": "the Word file",
  "markdown-text": "the text you gave",
  "source-text": "the text you gave",
  "pdf-extracted-text": "the text read from the PDF",
  "pdf-layout": "the PDF's lines, read where they sit on its pages",
};

const POLICY: Record<FidelityPolicy, { label: string; icon: typeof AlertTriangle; className: string }> = {
  unsupported: { label: "Left out", icon: XCircle, className: "text-red-600 dark:text-red-400" },
  blocked: { label: "Refused", icon: CircleSlash, className: "text-red-600 dark:text-red-400" },
  lossy: { label: "Changed", icon: AlertTriangle, className: "text-amber-600 dark:text-amber-400" },
  detected_not_editable: { label: "Kept for export", icon: Archive, className: "text-sky-600 dark:text-sky-400" },
  detected_preserved: { label: "Kept", icon: CheckCircle2, className: "text-green-600 dark:text-green-400" },
  not_detected: { label: "Not checked", icon: HelpCircle, className: "text-zinc-500" },
};
const ORDER: FidelityPolicy[] = ["unsupported", "blocked", "lossy", "detected_not_editable", "detected_preserved", "not_detected"];

const DIFFERENCE: Record<ContentDifference["kind"], string> = { missing: "Missing", added: "Added", changed: "Changed", moved: "Moved" };

const ASPECT: Record<PdfAspectConfidence["aspect"], string> = {
  text: "Text",
  paragraphs: "Paragraphs",
  headings: "Headings",
  lists: "Lists",
  captions: "Captions",
  tables: "Tables",
  columns: "Columns",
  pictures: "Pictures",
  readingOrder: "Reading order",
};

const percent = (value: number) => `${Math.round(value * 100)}%`;

/** "Imported from PDF" with how sure the conversion is, aspect by aspect (brief §88, §93; P2E-005/P2E-007). */
function PdfConversionSummary({ conversion }: { conversion: PdfConversion }) {
  const mode = conversion.mode === "layout" ? "layout-focused" : "editable document";
  const tone = conversion.confidence >= 0.75 ? "text-green-700 dark:text-green-400" : conversion.confidence >= 0.6 ? "text-amber-700 dark:text-amber-400" : "text-red-700 dark:text-red-400";
  return (
    <section aria-label="PDF conversion" className="rounded-lg bg-zinc-50 p-3 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-zinc-800">
      <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
        Imported from PDF <span className="font-normal text-zinc-500">· {conversion.rebuilt ? mode : "text only"}</span>
      </h3>
      <p className="mt-0.5 text-xs text-zinc-600 dark:text-zinc-400">
        Conversion confidence <span className={`font-semibold ${tone}`}>{percent(conversion.confidence)}</span>
        {conversion.lowConfidenceBlocks > 0 &&
          ` · ${conversion.lowConfidenceBlocks} of ${conversion.blocks} blocks are guesses worth a look (marked in the Structure panel)`}
      </p>
      <ul className="mt-2 flex flex-col gap-1">
        {conversion.aspects.map((aspect) => (
          <li key={aspect.aspect} className="text-xs text-zinc-600 dark:text-zinc-400">
            <span className="font-medium text-zinc-800 dark:text-zinc-200">{ASPECT[aspect.aspect]}</span> {percent(aspect.confidence)}
            {aspect.note && <span className="block opacity-80">{aspect.note}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The one-line verdict: "No content changes" only when the word comparison proved
 * it and nothing else (a header's text, a picture) was left out. */
export function contentVerdict(report: FidelityReport | null): { tone: "good" | "warn" | "none"; text: string } {
  if (!report || report.contentStatus === "unverified") return { tone: "none", text: "Content not verified" };
  if (report.contentStatus === "changed") return { tone: "warn", text: "Content differs from the source" };
  if (report.contentLossCount > 0) return { tone: "warn", text: "Body text complete, some content left out" };
  return { tone: "good", text: "No content changes" };
}

function Verdict({ report }: { report: FidelityReport | null }) {
  const verdict = contentVerdict(report);
  const content = report?.content ?? null;
  const tone = {
    good: "bg-green-50 text-green-800 ring-green-600/20 dark:bg-green-950/40 dark:text-green-300",
    warn: "bg-amber-50 text-amber-800 ring-amber-600/20 dark:bg-amber-950/40 dark:text-amber-300",
    none: "bg-zinc-50 text-zinc-700 ring-zinc-400/20 dark:bg-zinc-900 dark:text-zinc-300",
  }[verdict.tone];
  const source = content ? (SOURCE_LABEL[content.method] ?? "the source") : null;
  let detail = "This document wasn't made from a file or text the app could compare it with.";
  if (content?.verified) detail = `All ${content.sourceWords.toLocaleString()} words of ${source} are in the document, in the same order.`;
  else if (content) {
    const parts = [
      content.missing && `${content.missing.toLocaleString()} missing`,
      content.added && `${content.added.toLocaleString()} added`,
      content.moved && `${content.moved.toLocaleString()} moved`,
    ].filter(Boolean);
    detail = `Compared word by word with ${source}: ${parts.join(", ")}.`;
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
  if (samples.length === 0) return null;
  return (
    <section>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500">Where the words differ</h3>
      <ul className="flex flex-col gap-1.5">
        {samples.map((sample, index) => (
          <li key={index} className="text-xs text-zinc-600 dark:text-zinc-400">
            <span className="font-medium text-zinc-800 dark:text-zinc-200">{DIFFERENCE[sample.kind]}:</span>{" "}
            {sample.context && <span className="opacity-70">…{sample.context} </span>}
            {sample.source && <del className="text-red-700 dark:text-red-400">{sample.source}</del>}
            {sample.source && sample.result && " → "}
            {sample.result && <ins className="text-green-700 no-underline dark:text-green-400">{sample.result}</ins>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Item({ item, onShow }: { item: FidelityItem; onShow: (id: string) => void }) {
  const policy = POLICY[item.policy];
  const Icon = policy.icon;
  return (
    <li className="flex items-start gap-2">
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${policy.className}`} aria-label={policy.label} />
      <span className="min-w-0 text-xs text-zinc-600 dark:text-zinc-400">
        <span className="block text-sm text-zinc-800 dark:text-zinc-200">
          {item.reason}
          {item.count > 1 && <span className="ml-1 text-xs text-zinc-500">×{item.count}</span>}
        </span>
        <span className="block">
          {policy.label}
          {item.contentChanged && " · content"}
        </span>
        {item.sourceState && <span className="block truncate" title={item.sourceState}>Was: {item.sourceState}</span>}
        {item.newState && <span className="block truncate" title={item.newState}>Now: {item.newState}</span>}
        {item.elementIds.length > 0 && (
          <span className="mt-0.5 flex flex-wrap gap-1">
            {item.elementIds.slice(0, 8).map((id, index) => (
              <button key={id} type="button" onClick={() => onShow(id)} className="rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700">
                Show {index + 1}
              </button>
            ))}
          </span>
        )}
      </span>
    </li>
  );
}

/**
 * The "Проверка" rail panel (brief §17): the Document Fidelity Report of the
 * import -- whether every word of the source made it into the document (checked,
 * never assumed), and each thing that was changed, left out or only kept for export.
 */
/** What the editor holds that the document can't keep: saving goes on without it. */
function WhileEditing({ notes }: { notes: string[] }) {
  if (notes.length === 0) return null;
  const policy = POLICY.lossy;
  return (
    <section>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500">While editing</h3>
      <ul className="flex flex-col gap-3">
        {notes.map((text) => (
          <li key={text} className="flex items-start gap-2">
            <policy.icon className={`mt-0.5 h-4 w-4 shrink-0 ${policy.className}`} aria-label="Not kept" />
            <span className="min-w-0 text-sm text-zinc-800 dark:text-zinc-200">
              {text}
              <span className="block text-xs text-zinc-500">Shown in the editor until the document is opened again; not saved.</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function FidelityPanel() {
  const { document, editor, notKept, change } = useDocumentEditor();
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
        <TrackedChangesChoice choice={document.trackedChanges} onChoose={(choice) => change((id) => setTrackedChanges(id, choice))} />
      )}
      {report?.content && !report.content.verified && <Differences samples={report.content.samples} />}
      {items.length > 0 && (
        <section>
          <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500">
            {report!.reviewCount > 0 ? `${report!.reviewCount} to review` : "What the import noted"}
          </h3>
          <ul className="flex flex-col gap-3">
            {items.map((item) => (
              <Item key={`${item.feature}:${item.reason}`} item={item} onShow={show} />
            ))}
          </ul>
        </section>
      )}
      {report && items.length === 0 && report.content?.verified && <p className="text-xs text-zinc-500">Nothing was changed or left out on import.</p>}
      <WhileEditing notes={notKept} />
    </div>
  );
}
