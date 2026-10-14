"use client";

import { AlertTriangle, ArrowLeft, ChevronDown, ChevronUp } from "lucide-react";
import { useState, type CSSProperties } from "react";

import { TrackedChangesChoice } from "@/components/TrackedChangesChoice";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { fieldClasses } from "@/components/ui/TextField";
import { visibleText } from "@/editor/hiddenText";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import { renameDocument, setTrackedChanges, updateContent } from "@/services/api";
import type { Document, Element } from "@/types/document";

import { BLOCK_KINDS, canChangeKind, canMoveSection, kindOf, moveSection, structureChanged, withKind, type BlockKind } from "./structureEdits";

/** Below this the analysis itself says it wasn't sure (the editor's Structure panel uses the same line). */
const UNSURE = 0.6;
/** Long documents: the first blocks at once, the rest on request. */
const FIRST_BLOCKS = 40;
const PREVIEW_CHARS = 110;

function preview(element: Element): string {
  const text = visibleText(element).replace(/\s+/g, " ").trim();
  return text.length > PREVIEW_CHARS ? `${text.slice(0, PREVIEW_CHARS)}…` : text;
}

/** How far a block sits in: a heading by its level, anything else under the heading above it. */
function indents(elements: Element[]): number[] {
  let under = 0;
  return elements.map((element) => {
    if (element.type === "heading") {
      under = Math.min(Math.max(element.level ?? 1, 1), 3);
      return under - 1;
    }
    return under;
  });
}

/**
 * Step 2: what the import found, for the user to confirm before any look is applied (S2-020). Kinds and
 * sections can be changed; the words can't -- the editor is for that. Nothing is saved until "Confirm",
 * and then once: the project's name if it changed, the blocks with PUT /content if their kind or order did.
 */
type Filter = "all" | "headings" | "unsure";

const isUnsureBlock = (element: Element) => element.confidence != null && element.confidence < UNSURE;

export function StructureReview({
  document,
  onDocument,
  onConfirmed,
  onBack,
}: {
  document: Document;
  onDocument: (document: Document) => void;
  onConfirmed: (document: Document) => void;
  onBack?: () => void;
}) {
  const { m } = useI18n();
  const t = m.create.structure;
  const [title, setTitle] = useState(document.metadata.title);
  const [elements, setElements] = useState(document.elements);
  const [showAll, setShowAll] = useState(document.elements.length <= FIRST_BLOCKS);
  const [filter, setFilter] = useState<Filter>("all");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const headings = elements.filter((element) => element.type === "heading").length;
  const paragraphs = elements.filter((element) => element.type === "paragraph").length;
  const unsure = elements.filter(isUnsureBlock).length;
  const depth = indents(elements);
  // Each block with its place in the document (its depth), then the filter, then the first-blocks limit.
  const matching = elements
    .map((element, index) => ({ element, index }))
    .filter(({ element }) => filter === "all" || (filter === "headings" ? element.type === "heading" : isUnsureBlock(element)));
  const limited = filter === "all" && !showAll;
  const shown = limited ? matching.slice(0, FIRST_BLOCKS) : matching;
  const filters: { value: Filter; label: string }[] = [
    { value: "all", label: m.flow.filters.all },
    { value: "headings", label: m.flow.filters.headings },
    ...(unsure > 0 ? [{ value: "unsure" as const, label: format(m.flow.filters.unsure, { count: unsure }) }] : []),
  ];

  async function confirm() {
    setSaving(true);
    setError(null);
    try {
      let latest = document;
      const name = title.trim();
      if (name && name !== document.metadata.title) latest = await renameDocument(document.id, name);
      // styles []: the formatting the import gave each block stays as it is (set_direct_styles adds, never clears).
      if (structureChanged(document.elements, elements)) latest = await updateContent(document.id, elements);
      onConfirmed(latest);
    } catch (err) {
      setError(err instanceof Error ? err.message : m.create.error);
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 sm:gap-5">
      <label className="flex flex-col gap-1.5 text-sm font-medium text-foreground">
        {t.projectName}
        <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} className={fieldClasses} />
      </label>

      <div className="flex flex-col gap-1 text-sm">
        <p className="text-foreground">{format(t.summary, { headings, paragraphs, other: elements.length - headings - paragraphs })}</p>
        {unsure > 0 && (
          <p className="flex items-center gap-1.5 text-warning">
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
            {format(t.unsure, { count: unsure })}
          </p>
        )}
      </div>

      {elements.length > 0 && (
        <div role="radiogroup" aria-label={m.flow.filterLabel} className="flex flex-wrap gap-1.5">
          {filters.map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={filter === option.value}
              onClick={() => setFilter(option.value)}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                filter === option.value ? "border-accent bg-accent-soft text-foreground" : "border-line bg-surface text-muted hover:text-foreground"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}

      {elements.length === 0 ? (
        <Notice>{t.empty}</Notice>
      ) : shown.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-line-strong px-4 py-6 text-center text-sm text-muted">{m.flow.noneToShow}</p>
      ) : (
        <section aria-label={t.outline} className="rounded-2xl border border-line bg-surface shadow-card">
          <ul className="divide-y divide-line">
            {shown.map(({ element, index }) => {
              const text = preview(element);
              const kind = kindOf(element);
              const isUnsure = isUnsureBlock(element);
              const isHeading = element.type === "heading";
              return (
                <li
                  key={element.id}
                  // Indented by depth: half as much on a phone, so the text keeps its room.
                  className="flex items-center gap-2 py-2 pe-3 ps-[calc(var(--depth)*0.625rem+0.75rem)] sm:gap-3 sm:pe-4 sm:ps-[calc(var(--depth)*1.25rem+1rem)]"
                  style={{ "--depth": depth[index] } as CSSProperties}
                >
                  {canChangeKind(element) && kind ? (
                    <select
                      value={kind}
                      onChange={(e) => setElements((current) => withKind(current, element.id, e.target.value as BlockKind))}
                      aria-label={format(t.kindLabel, { text: text || "…" })}
                      className="h-8 w-28 shrink-0 rounded-lg sm:w-32 border border-line bg-surface px-2 text-xs text-foreground focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
                    >
                      {BLOCK_KINDS.map((option) => (
                        <option key={option} value={option}>
                          {t.kinds[option]}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="w-28 shrink-0 text-xs text-muted sm:w-32">{t.blocks[element.type as keyof typeof t.blocks] ?? t.blocks.other}</span>
                  )}
                  <span className={`min-w-0 flex-1 truncate text-sm ${isHeading ? "font-semibold text-foreground" : "text-muted"}`}>{text}</span>
                  {isUnsure && (
                    <span className="shrink-0 rounded-full bg-warning-soft px-2 py-0.5 text-xs font-medium text-warning">{t.check}</span>
                  )}
                  {isHeading && (
                    <span className="flex shrink-0 gap-0.5">
                      <button
                        type="button"
                        onClick={() => setElements((current) => moveSection(current, element.id, "up"))}
                        disabled={!canMoveSection(elements, element.id, "up")}
                        aria-label={format(t.moveUp, { text })}
                        className="flex h-7 w-7 items-center justify-center rounded-md text-muted hover:bg-surface-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-30"
                      >
                        <ChevronUp className="h-4 w-4" aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setElements((current) => moveSection(current, element.id, "down"))}
                        disabled={!canMoveSection(elements, element.id, "down")}
                        aria-label={format(t.moveDown, { text })}
                        className="flex h-7 w-7 items-center justify-center rounded-md text-muted hover:bg-surface-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-30"
                      >
                        <ChevronDown className="h-4 w-4" aria-hidden="true" />
                      </button>
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
          {limited && matching.length > FIRST_BLOCKS && (
            <button type="button" onClick={() => setShowAll(true)} className="w-full border-t border-line px-4 py-2.5 text-sm font-medium text-accent hover:bg-surface-muted">
              {format(t.showAll, { count: elements.length })}
            </button>
          )}
        </section>
      )}

      {document.trackedChanges && document.sourcePackage && (
        <TrackedChangesChoice choice={document.trackedChanges} onChoose={async (choice, discardEdits) => onDocument(await setTrackedChanges(document.id, choice, { discardEdits }))} />
      )}

      {error && <Notice tone="error">{error}</Notice>}
      <p className="text-xs text-muted">{t.draftNote}</p>
      {/* Always in reach on a long outline: sticks to the bottom of the screen while scrolling. */}
      <div className="sticky bottom-0 z-10 -mx-4 flex items-center justify-between gap-3 border-t border-line bg-background/95 px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:p-0">
        {onBack ? (
          <Button type="button" variant="ghost" onClick={onBack} disabled={saving}>
            <ArrowLeft className="h-4 w-4" aria-hidden="true" /> {m.create.back}
          </Button>
        ) : (
          <span />
        )}
        <Button type="button" size="lg" onClick={confirm} loading={saving} loadingLabel={t.saving}>
          {t.confirm}
        </Button>
      </div>
    </div>
  );
}
