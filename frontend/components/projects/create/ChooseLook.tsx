"use client";

import { ArrowLeft, Check, CheckCircle2, FileSearch, Lightbulb, Sparkles } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { JobProgressBar } from "@/components/JobProgressBar";
import { ReferenceStyleSummary } from "@/components/ReferenceStyleSummary";
import { TemplatePreviewSample } from "@/components/TemplatePreviewSample";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { fieldClasses } from "@/components/ui/TextField";
import { useI18n } from "@/i18n/I18nProvider";
import { format, plural } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages/en";
import { createTemplate, extractReferenceStyle } from "@/services/api";
import type { JobProgress, ReferenceStyle, Template } from "@/types/document";

import type { Evidence, LookSuggestion } from "./recommendLook";

export type LookChoice = { kind: "template"; id: string } | { kind: "reference" } | { kind: "none" };

/** What the step starts on: a template the link named (?template=), the reference option (?reference=1),
 * the workspace's default template, the suggestion for this document, or nothing. A default the
 * workspace chose comes before a suggestion: it was a decision, the suggestion is only advice. */
export function initialLook(templates: Template[], requested: string | null, reference: boolean, suggested?: string | null): LookChoice {
  if (reference) return { kind: "reference" };
  const id =
    templates.find((template) => template.id === requested)?.id ??
    templates.find((template) => template.isDefault)?.id ??
    templates.find((template) => template.id === suggested)?.id;
  return id ? { kind: "template", id } : { kind: "none" };
}

/** The evidence in words: "it mentions “report”, “budget” and it has 2 tables". */
export function reasonsText(evidence: Evidence[], t: Messages["flow"]): string {
  return evidence
    .map((item) => {
      if (item.kind === "words") return format(t.evidence.words, { words: item.words.map((word) => `“${word}”`).join(", ") });
      if (item.kind === "tables") return plural(item.count, t.evidence.tables);
      if (item.kind === "pictures") return plural(item.count, t.evidence.pictures);
      return format(t.evidence.headings, { count: item.count });
    })
    .join(t.and);
}

function Choice({ selected, onSelect, title, text, icon, children }: { selected: boolean; onSelect: () => void; title: ReactNode; text?: string; icon?: ReactNode; children?: ReactNode }) {
  const { m } = useI18n();
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`relative flex w-full flex-col rounded-2xl border p-3 text-left text-sm transition-[border-color,box-shadow,background-color] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
        selected ? "border-accent bg-accent-soft ring-2 ring-accent" : "border-line bg-surface hover:border-line-strong hover:shadow-card"
      }`}
    >
      <span className="flex items-center gap-3">
        {icon}
        <span className="min-w-0 flex-1">
          <span className="block font-medium text-foreground">{title}</span>
          {text && <span className="mt-0.5 block text-xs text-muted">{text}</span>}
        </span>
        {selected ? (
          <span className="flex shrink-0 items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-[11px] font-semibold text-white">
            <Check className="h-3 w-3" aria-hidden="true" /> {m.flow.selected}
          </span>
        ) : (
          <span className="h-5 w-5 shrink-0 rounded-full border-2 border-line-strong" aria-hidden="true" />
        )}
      </span>
      {children}
    </button>
  );
}

/**
 * Step 3: the look -- a template, the look of a reference Word file (saved as a template when applied, once),
 * or none; and, optionally, instructions in the user's words. Called AI only when a model is configured. A
 * suggestion for this document (built-in rules, M3.3) is shown with its reasons; choosing it is the person's.
 */
export function ChooseLook({
  templates,
  initial,
  suggestion,
  aiConfigured,
  onApply,
  onSkip,
  onBack,
  busy,
}: {
  templates: Template[];
  initial: LookChoice;
  suggestion?: LookSuggestion | null;
  aiConfigured: boolean;
  onApply: (look: { templateId?: string; instructions?: string }) => void;
  onSkip: () => void;
  onBack?: () => void;
  busy: boolean;
}) {
  const { m } = useI18n();
  const t = m.create.look;
  const [choice, setChoice] = useState<LookChoice>(initial);
  const [instructions, setInstructions] = useState("");
  const [referenceFile, setReferenceFile] = useState<File | null>(null);
  const [reference, setReference] = useState<ReferenceStyle | null>(null);
  const [readingProgress, setReadingProgress] = useState<JobProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The reference's look, saved as a template only when applied; kept so a retry doesn't save it twice.
  const savedReference = useRef<string | null>(null);

  const wanted = instructions.trim();
  const ready = choice.kind === "template" || (choice.kind === "reference" ? reference !== null : wanted.length > 0);
  const suggested = suggestion ? templates.find((template) => template.id === suggestion.templateId) : undefined;
  const suggestionChosen = choice.kind === "template" && choice.id === suggested?.id;

  async function readReference(file: File) {
    setReferenceFile(file);
    setReference(null);
    setError(null);
    savedReference.current = null;
    setReadingProgress({ stage: "queued", progress: 0 });
    try {
      setReference(await extractReferenceStyle(file, setReadingProgress));
    } catch (err) {
      setError(err instanceof Error ? err.message : t.reference.failed);
    } finally {
      setReadingProgress(null);
    }
  }

  async function apply() {
    setError(null);
    try {
      let templateId: string | undefined;
      if (choice.kind === "template") templateId = choice.id;
      if (choice.kind === "reference" && reference && referenceFile) {
        savedReference.current ??= (await createTemplate({ name: reference.suggestedName, description: format(m.templatesPage.lookOfDescription, { name: referenceFile.name }), styleSystem: reference.styleSystem })).id;
        templateId = savedReference.current;
      }
      onApply({ templateId, instructions: wanted || undefined });
    } catch (err) {
      setError(err instanceof Error ? err.message : m.create.error);
    }
  }

  return (
    <div className="flex flex-col gap-4 sm:gap-5">
      {suggestion && suggested && (
        <section aria-label={m.flow.suggested} className="flex flex-col gap-3 rounded-2xl border border-accent/30 bg-surface p-4 shadow-card sm:flex-row sm:items-center">
          <span className="hidden h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-tile-amber text-tile-amber-ink sm:flex">
            <Lightbulb className="h-5 w-5" aria-hidden="true" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-accent">{m.flow.suggested}</p>
            <p className="mt-0.5 text-sm font-semibold text-foreground">{suggested.name}</p>
            <p className="mt-0.5 text-sm text-muted">{format(m.flow.because, { reasons: reasonsText(suggestion.evidence, m.flow) })}</p>
            <p className="mt-1 text-xs text-muted">{m.flow.rulesNote}</p>
          </div>
          {suggestionChosen ? (
            <span className="flex items-center gap-1.5 self-start text-sm font-medium text-success sm:self-auto">
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> {m.flow.selected}
            </span>
          ) : (
            <Button type="button" variant="secondary" size="sm" onClick={() => setChoice({ kind: "template", id: suggested.id })} className="self-start sm:self-auto">
              {m.flow.useSuggestion}
            </Button>
          )}
        </section>
      )}

      <section className="flex flex-col gap-2" aria-label={t.templates}>
        <h2 className="text-sm font-semibold text-foreground">{t.templates}</h2>
        <div className="grid gap-2 sm:grid-cols-2">
          {templates.map((template) => (
            <Choice
              key={template.id}
              selected={choice.kind === "template" && choice.id === template.id}
              onSelect={() => setChoice({ kind: "template", id: template.id })}
              title={
                <>
                  {template.name}
                  {template.isDefault && <span className="ml-1.5 text-xs font-normal text-muted">({t.defaultTag})</span>}
                </>
              }
              text={template.description ?? undefined}
            >
              <TemplatePreviewSample styles={template.previewStyles} className="h-20 sm:h-24" />
            </Choice>
          ))}
        </div>
      </section>

      <div className="flex flex-col gap-2">
        <Choice selected={choice.kind === "reference"} onSelect={() => setChoice({ kind: "reference" })} title={t.reference.title} text={t.reference.text} icon={<FileSearch className="h-4 w-4 shrink-0 text-muted" aria-hidden="true" />} />
        {choice.kind === "reference" && (
          <div className="flex flex-col gap-2 rounded-2xl border border-line p-3">
            <input
              type="file"
              accept=".docx"
              aria-label={t.reference.fileLabel}
              onChange={(e) => {
                const picked = e.target.files?.[0];
                if (picked) void readReference(picked);
              }}
              className={`${fieldClasses} h-auto py-2 file:mr-3 file:rounded-lg file:border-0 file:bg-accent-soft file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-accent`}
            />
            {readingProgress && <JobProgressBar progress={readingProgress} label={format(t.reference.reading, { name: referenceFile?.name ?? "" })} />}
            {reference && <ReferenceStyleSummary reference={reference} />}
          </div>
        )}
        <Choice selected={choice.kind === "none"} onSelect={() => setChoice({ kind: "none" })} title={t.none.title} text={t.none.text} />
      </div>

      <label className="flex flex-col gap-1.5 text-sm font-medium text-foreground">
        {t.instructionsLabel}
        <textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} rows={3} maxLength={2000} placeholder={t.instructionsPlaceholder} className={`${fieldClasses} h-auto py-3 font-normal`} />
        <span className="flex items-start gap-1.5 text-xs font-normal text-muted">
          {aiConfigured && <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />}
          {aiConfigured ? t.instructionsAi : t.instructionsRules}
        </span>
      </label>

      {error && <Notice tone="error">{error}</Notice>}
      <div className="sticky bottom-0 z-10 -mx-4 flex flex-col-reverse gap-2 border-t border-line bg-background/95 px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:flex-row sm:items-center sm:border-0 sm:bg-transparent sm:p-0">
        {onBack && (
          <Button type="button" variant="ghost" onClick={onBack} disabled={busy} className="sm:mr-auto">
            <ArrowLeft className="h-4 w-4" aria-hidden="true" /> {m.create.back}
          </Button>
        )}
        <Button type="button" variant="secondary" size="lg" onClick={onSkip} disabled={busy}>
          {t.skip}
        </Button>
        <Button type="button" size="lg" onClick={apply} disabled={!ready} loading={busy}>
          {t.apply}
        </Button>
      </div>
    </div>
  );
}
