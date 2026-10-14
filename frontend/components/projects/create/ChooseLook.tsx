"use client";

import { CheckCircle2, FileSearch, Sparkles } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { JobProgressBar } from "@/components/JobProgressBar";
import { ReferenceStyleSummary } from "@/components/ReferenceStyleSummary";
import { TemplatePreviewSample } from "@/components/TemplatePreviewSample";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { fieldClasses } from "@/components/ui/TextField";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import { createTemplate, extractReferenceStyle } from "@/services/api";
import type { JobProgress, ReferenceStyle, Template } from "@/types/document";

export type LookChoice = { kind: "template"; id: string } | { kind: "reference" } | { kind: "none" };

/** What the step starts on: a template the link named (?template=), the reference option (?reference=1),
 * the workspace's default template, or nothing. */
export function initialLook(templates: Template[], requested: string | null, reference: boolean): LookChoice {
  if (reference) return { kind: "reference" };
  const id = templates.find((template) => template.id === requested)?.id ?? templates.find((template) => template.isDefault)?.id;
  return id ? { kind: "template", id } : { kind: "none" };
}

function Choice({ selected, onSelect, title, text, icon, children }: { selected: boolean; onSelect: () => void; title: ReactNode; text?: string; icon?: ReactNode; children?: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`flex w-full flex-col rounded-xl border p-3 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
        selected ? "border-accent bg-accent-soft" : "border-line bg-surface hover:border-line-strong"
      }`}
    >
      <span className="flex items-center gap-3">
        {icon}
        <span className="min-w-0 flex-1">
          <span className="block font-medium text-foreground">{title}</span>
          {text && <span className="mt-0.5 block text-xs text-muted">{text}</span>}
        </span>
        {selected && <CheckCircle2 className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />}
      </span>
      {children}
    </button>
  );
}

/**
 * Step 3: the look -- a template, the look of a reference Word file (saved as a template when applied, once),
 * or none; and, optionally, instructions in the user's words. Called AI only when a model is configured.
 */
export function ChooseLook({
  templates,
  initial,
  aiConfigured,
  onApply,
  onSkip,
  busy,
}: {
  templates: Template[];
  initial: LookChoice;
  aiConfigured: boolean;
  onApply: (look: { templateId?: string; instructions?: string }) => void;
  onSkip: () => void;
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
        savedReference.current ??= (await createTemplate({ name: reference.suggestedName, description: `The look of ${referenceFile.name}.`, styleSystem: reference.styleSystem })).id;
        templateId = savedReference.current;
      }
      onApply({ templateId, instructions: wanted || undefined });
    } catch (err) {
      setError(err instanceof Error ? err.message : m.create.error);
    }
  }

  return (
    <div className="flex flex-col gap-5">
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
              <TemplatePreviewSample styles={template.previewStyles} className="h-24" />
            </Choice>
          ))}
        </div>
      </section>

      <div className="flex flex-col gap-2">
        <Choice selected={choice.kind === "reference"} onSelect={() => setChoice({ kind: "reference" })} title={t.reference.title} text={t.reference.text} icon={<FileSearch className="h-4 w-4 shrink-0 text-muted" aria-hidden="true" />} />
        {choice.kind === "reference" && (
          <div className="flex flex-col gap-2 rounded-xl border border-line p-3">
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
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
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
