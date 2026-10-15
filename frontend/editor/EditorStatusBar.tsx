"use client";

import { CloudOff, Eye, EyeOff, FilePlus2, Minus, Plus, Scan } from "lucide-react";

import { contentVerdict } from "@/editor/panels/FidelityPanel";
import type { SaveStatus } from "@/editor/useAutoSave";
import { useI18n } from "@/i18n/I18nProvider";
import { format, plural } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages/en";
import type { FidelityReport } from "@/types/document";

const ZOOM_STEPS = [0.5, 0.75, 0.9, 1, 1.1, 1.25, 1.5];

type Words = Messages["edStatus"];

function SaveState({ status, problem, onRetry, t }: { status: SaveStatus; problem: string | null; onRetry: () => void; t: Words }) {
  switch (status) {
    case "pending":
      return <span className="text-muted">{t.pending}</span>;
    case "saving":
      return <span className="text-muted">{t.saving}</span>;
    case "saved":
      return <span className="text-muted">{t.saved}</span>;
    case "error":
      return (
        <span className="flex items-center gap-1.5 text-danger">
          {t.failed}
          <button type="button" onClick={onRetry} className="font-medium underline hover:no-underline">
            {t.retry}
          </button>
        </span>
      );
    case "offline":
      return (
        <span className="flex items-center gap-1 text-warning" title={t.offlineHint}>
          <CloudOff className="h-3.5 w-3.5" aria-hidden="true" />
          {t.offline}
        </span>
      );
    case "conflict":
      return <span className="text-warning">{t.conflict}</span>;
    case "unsupported":
      return (
        <span className="text-danger" title={format(t.unsupportedHint, { problem: problem ?? "" })}>
          {format(t.unsupported, { problem: problem ?? t.unsupportedDefault })}
        </span>
      );
    default:
      return null;
  }
}

/** The import's content check, when there was one: "No content changes" only if it was proven. */
function ImportCheck({ report, t }: { report: FidelityReport; t: Words }) {
  const verdict = contentVerdict(report, t.verdict);
  if (verdict.tone === "none") return null;
  const review = report.reviewCount > 0 ? format(t.toReviewSuffix, { count: report.reviewCount }) : "";
  return (
    <span className={`shrink-0 ${verdict.tone === "good" && !review ? "text-success" : "text-warning"}`} title={t.importHint}>
      {verdict.text}
      {review}
    </span>
  );
}

/** Formatting in the editor the document can't keep: saved without it, and said so. */
function NotKept({ notes, t }: { notes: string[]; t: Words }) {
  if (notes.length === 0) return null;
  return (
    <span className="shrink-0 text-warning" title={`${notes.join("\n")}\n${t.notKeptHint}`}>
      {plural(notes.length, t.notKept)}
    </span>
  );
}

/** AI changes waiting for review (the Review panel, the Instructions and Translate panels). */
function ToReview({ count, t }: { count: number; t: Words }) {
  if (count === 0) return null;
  return (
    <span className="shrink-0 text-warning" title={t.aiToReviewHint}>
      {plural(count, t.aiToReview)}
    </span>
  );
}

/** Document Health fixes waiting for review (HLTH-002): worked out by rules, not by an AI. */
function FixesToReview({ count, t }: { count: number; t: Words }) {
  if (count === 0) return null;
  return (
    <span className="shrink-0 text-warning" title={t.fixesHint}>
      {plural(count, t.fixesToReview)}
    </span>
  );
}

/** Word's hidden text (DOCX-025): kept and hidden; shown on the pages only on request. */
function HiddenText({ words, shown, onToggle, t }: { words: number; shown: boolean; onToggle: () => void; t: Words }) {
  if (words === 0) return null;
  const Icon = shown ? EyeOff : Eye;
  return (
    <button
      type="button"
      aria-pressed={shown}
      onClick={onToggle}
      title={t.hiddenHint}
      className="flex shrink-0 items-center gap-1 rounded px-2 py-1 text-foreground hover:bg-surface-muted hover:text-accent"
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {shown ? t.hideHidden : plural(words, t.showHidden)}
    </button>
  );
}

const quietButton = "flex h-7 items-center justify-center rounded text-muted hover:bg-surface-muted hover:text-foreground";

/**
 * The status bar under the pages (like Word's): add a page, the page count,
 * whether the typing is saved (корекции.docx §29), and zoom.
 */
export function EditorStatusBar({
  zoom,
  onZoomChange,
  onFitWidth,
  pageCount,
  onAddPage,
  saveStatus,
  saveProblem = null,
  notKept = [],
  proposalCount = 0,
  fixCount = 0,
  importReport = null,
  hiddenWords = 0,
  showHidden = false,
  onToggleHidden = () => {},
  onRetrySave,
}: {
  zoom: number;
  onZoomChange: (zoom: number) => void;
  onFitWidth: () => void;
  pageCount: number;
  onAddPage: () => void;
  saveStatus: SaveStatus;
  saveProblem?: string | null;
  notKept?: string[];
  proposalCount?: number;
  /** Document Health fixes waiting for review (counted apart from the AI's changes). */
  fixCount?: number;
  importReport?: FidelityReport | null;
  /** Words of Word's hidden text in the document, and whether the pages show them. */
  hiddenWords?: number;
  showHidden?: boolean;
  onToggleHidden?: () => void;
  onRetrySave: () => void;
}) {
  const { m } = useI18n();
  const t = m.edStatus;
  const index = ZOOM_STEPS.findIndex((step) => step >= zoom);

  function step(delta: number) {
    const nextIndex = Math.min(ZOOM_STEPS.length - 1, Math.max(0, (index === -1 ? ZOOM_STEPS.length - 1 : index) + delta));
    onZoomChange(ZOOM_STEPS[nextIndex]);
  }

  return (
    <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-t border-line bg-surface px-4 text-xs text-muted">
      <div className="flex min-w-0 items-center gap-3">
        <button type="button" onClick={onAddPage} className="flex shrink-0 items-center gap-1 rounded px-2 py-1 text-foreground hover:bg-surface-muted hover:text-accent">
          <FilePlus2 className="h-3.5 w-3.5" aria-hidden="true" />
          {t.newPage}
        </button>
        <span className="h-4 w-px shrink-0 bg-line" aria-hidden="true" />
        <span className="shrink-0">{plural(pageCount, t.pages)}</span>
        <span role="status" className="min-w-0 truncate">
          <SaveState status={saveStatus} problem={saveProblem} onRetry={onRetrySave} t={t} />
        </span>
        <NotKept notes={notKept} t={t} />
        <ToReview count={proposalCount} t={t} />
        <FixesToReview count={fixCount} t={t} />
        <HiddenText words={hiddenWords} shown={showHidden} onToggle={onToggleHidden} t={t} />
        {importReport && <ImportCheck report={importReport} t={t} />}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <button type="button" aria-label={t.zoomOut} title={t.zoomOut} onClick={() => step(-1)} className={`${quietButton} w-7`}>
          <Minus className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
        <span className="w-10 text-center tabular-nums">{Math.round(zoom * 100)}%</span>
        <button type="button" aria-label={t.zoomIn} title={t.zoomIn} onClick={() => step(1)} className={`${quietButton} w-7`}>
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
        <span className="mx-1 h-5 w-px bg-line" aria-hidden="true" />
        <button type="button" aria-label={t.fitWidth} title={t.fitWidth} onClick={onFitWidth} className={`${quietButton} gap-1 px-2`}>
          <Scan className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="hidden sm:inline">{t.fitWidth}</span>
        </button>
      </div>
    </div>
  );
}
