"use client";

import { Check } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Notice } from "@/components/ui/Notice";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import { formatDocument, importFile, importText } from "@/services/api";
import { useAiAvailability, useBilling, useTemplates } from "@/services/queries";
import type { Document, JobProgress, Template } from "@/types/document";

import { AddContent, type ContentInput } from "./AddContent";
import { ChooseLook, initialLook } from "./ChooseLook";
import { advance, formatStages, importStages, ProcessingView, type Processing, type ProcessingStage } from "./ProcessingView";
import { StructureReview } from "./StructureReview";

type Step = "content" | "structure" | "look";
const STEPS: Step[] = ["content", "structure", "look"];
const NO_TEMPLATES: Template[] = [];

function Stepper({ step }: { step: Step }) {
  const { m } = useI18n();
  const current = STEPS.indexOf(step);
  return (
    <ol className="flex items-center gap-2 text-xs font-medium" aria-label={format(m.create.stepOf, { step: current + 1 })}>
      {STEPS.map((name, index) => (
        <li key={name} className="flex min-w-0 flex-1 items-center gap-2" aria-current={index === current ? "step" : undefined}>
          <span
            className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
              index < current ? "bg-success text-white" : index === current ? "bg-accent text-white" : "bg-surface-muted text-muted"
            }`}
          >
            {index < current ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : index + 1}
          </span>
          <span className={`truncate ${index === current ? "text-foreground" : "text-muted"} max-sm:sr-only`}>{m.create.steps[name]}</span>
          {index < STEPS.length - 1 && <span className="h-px min-w-4 flex-1 bg-line" aria-hidden="true" />}
        </li>
      ))}
    </ol>
  );
}

/**
 * The 2.0 document flow (S2-020): add content -> the import job reads it -> check the structure -> choose the
 * look -> the format job -> the editor. Built on the same APIs as the 1.x wizard; once imported, the document
 * is already saved, so leaving midway keeps it as a draft.
 */
export function DocumentFlow() {
  const { m } = useI18n();
  const router = useRouter();
  const params = useSearchParams();
  const templates = useTemplates();
  const maxFileMb = useBilling().data?.plan.entitlements.maxDocumentSizeMb;
  const aiConfigured = useAiAvailability().data === true;

  const [step, setStep] = useState<Step>("content");
  const [processing, setProcessing] = useState<Processing | null>(null);
  const [document, setDocument] = useState<Document | null>(null);
  const [formatting, setFormatting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Shows a job's real progress; a stage once reached stays reached. */
  function follow(title: Processing["title"], stages: ProcessingStage[]) {
    let state: Processing = { title, stages, current: { stage: "queued", progress: 0 }, reached: -1 };
    setProcessing(state);
    return (current: JobProgress) => {
      state = advance(state, current);
      setProcessing(state);
    };
  }

  async function addContent(input: ContentInput) {
    setError(null);
    const show = follow("importTitle", importStages(input.method, input.method === "upload" ? input.file : null));
    try {
      const imported = input.method === "paste" ? await importText(input.text, undefined, show) : await importFile(input.file, undefined, show, { autolink: input.autolink, pdfMode: input.pdfMode });
      setDocument(imported);
      setStep("structure");
    } catch (err) {
      setError(err instanceof Error ? err.message : m.create.error);
    } finally {
      setProcessing(null);
    }
  }

  async function applyLook(look: { templateId?: string; instructions?: string }) {
    if (!document) return;
    setError(null);
    setFormatting(true);
    const show = follow("formatTitle", formatStages(Boolean(look.instructions)));
    try {
      // A new document has no manual overrides yet, so this first formatting can't conflict with any.
      await formatDocument(document.id, { templateId: look.templateId, instructionsText: look.instructions, onProgress: show });
      router.push(`/documents/${document.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : m.create.error);
      setProcessing(null);
      setFormatting(false);
    }
  }

  const titles = { content: m.create.content, structure: m.create.structure, look: m.create.look };
  const heading = titles[step];

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6 sm:py-10">
      {processing ? (
        <ProcessingView processing={processing} />
      ) : (
        <>
          <Stepper step={step} />
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-accent">{format(m.create.stepOf, { step: STEPS.indexOf(step) + 1 })}</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{heading.title}</h1>
            <p className="mt-1.5 text-sm text-muted">{heading.subtitle}</p>
          </div>
          {error && <Notice tone="error">{error}</Notice>}
          {step === "content" && <AddContent initialMethod={params.get("mode") === "upload" ? "upload" : "paste"} maxFileMb={maxFileMb} onSubmit={addContent} />}
          {step === "structure" && document && (
            // A tracked-changes choice reads the document again: the review starts over from what it now is.
            <StructureReview key={document.revision} document={document} onDocument={setDocument} onConfirmed={(confirmed) => {
                setDocument(confirmed);
                setStep("look");
              }}
            />
          )}
          {step === "look" && document && !templates.isPending && (
            <ChooseLook
              templates={templates.data ?? NO_TEMPLATES}
              initial={initialLook(templates.data ?? NO_TEMPLATES, params.get("template"), params.get("reference") === "1")}
              aiConfigured={aiConfigured}
              onApply={applyLook}
              onSkip={() => router.push(`/documents/${document.id}`)}
              busy={formatting}
            />
          )}
        </>
      )}
    </main>
  );
}
