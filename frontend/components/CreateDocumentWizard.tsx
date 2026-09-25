"use client";

import { CheckCircle2, Circle, ClipboardPaste, FileSearch, Loader2, Upload } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useRef, useState, type ReactNode } from "react";

import { JobProgressBar } from "@/components/JobProgressBar";
import { ReferenceStyleSummary } from "@/components/ReferenceStyleSummary";
import { StructurePanel } from "@/editor/panels/StructurePanel";
import { TemplatePreviewSample } from "@/components/TemplatePreviewSample";
import { createTemplate, extractReferenceStyle, formatDocument, importFile, importText } from "@/services/api";
import { useBilling, useTemplates } from "@/services/queries";
import type { Document, JobProgress, ReferenceStyle, Template } from "@/types/document";

const NO_TEMPLATES: Template[] = [];

type Step = 1 | 2 | 3;
type StartMethod = "paste" | "upload";
type FormattingChoice = "template-only" | "with-instructions" | "later";
/** `reached`: the furthest step the job has got to (-1 before the first), so a
 * "queued" report after the upload never moves a finished step back. */
type Processing = { title: string; steps: { stage: string; label: string }[]; current: JobProgress; reached: number };

/** The steps each kind of work goes through on the backend (app/jobs), in order. */
function importSteps(method: StartMethod, file: File | null): Processing["steps"] {
  const extension = file?.name.split(".").pop()?.toLowerCase();
  if (method === "paste") return [{ stage: "analyzing", label: "Analyzing the structure" }, { stage: "finalizing", label: "Saving the document" }];
  return [
    { stage: "uploading", label: "Uploading" },
    ...(extension === "txt" ? [] : [{ stage: "parsing", label: "Reading the file" }]),
    ...(extension === "docx" ? [] : [{ stage: "analyzing", label: "Analyzing the structure" }]),
    { stage: "finalizing", label: "Saving the document" },
  ];
}

function formattingSteps(withInstructions: boolean): Processing["steps"] {
  return [
    ...(withInstructions ? [{ stage: "analyzing", label: "Reading your instructions" }] : []),
    { stage: "formatting", label: "Applying formatting" },
  ];
}

/**
 * What the backend job is really doing (корекции.docx §53): the stage and
 * percentage it records as each step finishes, polled -- never a timer.
 */
function ProcessingScreen({ processing }: { processing: Processing }) {
  const { steps, current, reached } = processing;

  return (
    <div className="flex flex-col gap-6 py-12">
      <h1 className="text-center text-2xl font-semibold text-zinc-900 dark:text-zinc-50">{processing.title}</h1>
      <div className="mx-auto flex flex-col gap-3">
        {steps.map((step, index) => {
          const done = index < reached;
          const active = index === reached;
          return (
            <div key={step.stage} className="flex items-center gap-3 text-sm">
              {done ? (
                <CheckCircle2 className="h-5 w-5 shrink-0 text-accent" aria-hidden="true" />
              ) : active ? (
                <Loader2 className="h-5 w-5 shrink-0 animate-spin text-accent" aria-hidden="true" />
              ) : (
                <Circle className="h-5 w-5 shrink-0 text-zinc-300 dark:text-zinc-700" aria-hidden="true" />
              )}
              <span className={done || active ? "text-zinc-900 dark:text-zinc-50" : "text-zinc-400 dark:text-zinc-600"}>{step.label}</span>
            </div>
          );
        })}
      </div>
      <div className="mx-auto w-full max-w-xs">
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={current.progress}
          aria-label={processing.title}
          className="h-1.5 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800"
        >
          <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${current.progress}%` }} />
        </div>
        <p className="mt-2 text-center text-xs text-zinc-500 dark:text-zinc-400">{reached < 0 ? "Waiting to start…" : `${current.progress}%`}</p>
      </div>
    </div>
  );
}

/**
 * Sits between "reading" and "formatting" -- shows what structure analysis
 * actually detected (real Element.confidence data via StructurePanel, the
 * same component the editor's own Structure tab uses) so the user can catch
 * a misread before formatting is applied, rather than only finding out once
 * they're already in the editor.
 */
function StructureReviewScreen({ document, onContinue, continuing, error }: { document: Document; onContinue: () => void; continuing: boolean; error: string | null }) {
  const headingCount = document.elements.filter((el) => el.type === "heading").length;
  const paragraphCount = document.elements.filter((el) => el.type === "paragraph").length;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="text-xs font-medium tracking-wide text-accent uppercase">Structure detected</p>
        <h1 className="mt-1 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">Here&rsquo;s what we found</h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          {headingCount} heading{headingCount === 1 ? "" : "s"}, {paragraphCount} paragraph{paragraphCount === 1 ? "" : "s"}. Review the outline below before continuing.
        </p>
      </div>
      <div className="max-h-80 overflow-y-auto rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
        <StructurePanel elements={document.elements} />
      </div>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={onContinue}
          disabled={continuing}
          className="rounded-full bg-accent px-6 py-2.5 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {continuing ? "Continuing..." : "Looks good, continue"}
        </button>
      </div>
    </div>
  );
}

const inputClass =
  "w-full rounded-lg border border-zinc-300 bg-white p-4 text-sm text-zinc-900 shadow-sm focus:border-accent focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100";

function RadioCard({
  selected,
  onSelect,
  title,
  description,
  icon,
  preview,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  description?: string;
  icon?: ReactNode;
  preview?: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`flex-1 rounded-lg border px-4 py-3 text-left text-sm transition-colors ${
        selected
          ? "border-accent bg-accent/5 text-zinc-900 dark:text-zinc-50"
          : "border-zinc-200 text-zinc-600 hover:border-zinc-300 dark:border-zinc-800 dark:text-zinc-400"
      }`}
    >
      <span className="flex items-center gap-3">
        {icon}
        <span className="flex-1">
          <span className="block font-medium">{title}</span>
          {description && <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">{description}</span>}
        </span>
        {selected && <CheckCircle2 className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />}
      </span>
      {preview}
    </button>
  );
}

function StepHeader({ step, title }: { step: Step; title: string }) {
  return (
    <div>
      <p className="text-xs font-medium tracking-wide text-accent uppercase">Step {step} of 3</p>
      <h1 className="mt-1 text-2xl font-semibold text-zinc-900 dark:text-zinc-50">{title}</h1>
    </div>
  );
}

function NavRow({ onBack, onNext, nextLabel, nextDisabled }: { onBack?: () => void; onNext: () => void; nextLabel: string; nextDisabled?: boolean }) {
  return (
    <div className="flex items-center justify-between pt-2">
      {onBack ? (
        <button type="button" onClick={onBack} className="text-sm font-medium text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200">
          Back
        </button>
      ) : (
        <span />
      )}
      <button
        type="button"
        onClick={onNext}
        disabled={nextDisabled}
        className="rounded-full bg-accent px-6 py-2.5 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {nextLabel}
      </button>
    </div>
  );
}

/**
 * Progressive 3-step creation screen (doc type -> start method -> formatting
 * method -> one final Continue). Importing and formatting run as background
 * jobs (importText/importFile, formatDocument) whose real progress the
 * processing screen shows.
 */
export function CreateDocumentWizard() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [step, setStep] = useState<Step>(1);

  const { data: templates = NO_TEMPLATES } = useTemplates();
  const maxFileMb = useBilling().data?.plan.entitlements.maxDocumentSizeMb;
  // ?template=<id> (the dashboard's "Use") preselects a template; ?reference=1 the reference option.
  const [pickedTemplateId, setTemplateId] = useState<string | null>(searchParams.get("template"));
  const [noTemplate, setNoTemplate] = useState(false);
  // Format by Example: the look of a reference .docx instead of a template.
  const [useReference, setUseReference] = useState(searchParams.get("reference") === "1");
  const [referenceFile, setReferenceFile] = useState<File | null>(null);
  const [reference, setReference] = useState<ReferenceStyle | null>(null);
  // The reading job's progress; null when not reading.
  const [referenceProgress, setReferenceProgress] = useState<JobProgress | null>(null);
  const [referenceError, setReferenceError] = useState<string | null>(null);
  // Saved as a template only when formatting runs; kept so a retry doesn't save it twice.
  const referenceTemplateId = useRef<string | null>(null);
  // The workspace's default template is preselected until something else is picked.
  const defaultTemplateId = templates.find((template) => template.isDefault)?.id ?? null;
  const picked = templates.some((template) => template.id === pickedTemplateId) ? pickedTemplateId : null;
  const templateId = noTemplate || useReference ? null : (picked ?? defaultTemplateId);
  const hasTemplate = Boolean(templateId);
  const hasReference = useReference && reference !== null;
  const hasFormattingSource = hasTemplate || hasReference;

  const [startMethod, setStartMethod] = useState<StartMethod>(searchParams.get("mode") === "upload" ? "upload" : "paste");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const [formattingChoice, setFormattingChoice] = useState<FormattingChoice>("template-only");
  const [instructionsText, setInstructionsText] = useState("");

  const [processing, setProcessing] = useState<Processing | null>(null);
  const [reviewDocument, setReviewDocument] = useState<Document | null>(null);
  const [reviewContinuing, setReviewContinuing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Derived rather than synced via an effect, so going back and dropping the
  // template falls back to "with-instructions" without an extra render pass,
  // and re-picking a template naturally restores the original raw choice.
  const effectiveFormattingChoice: FormattingChoice = !hasFormattingSource && formattingChoice === "template-only" ? "with-instructions" : formattingChoice;

  async function readReference(picked: File) {
    setReferenceFile(picked);
    setReference(null);
    setReferenceError(null);
    setReferenceProgress({ stage: "queued", progress: 0 });
    referenceTemplateId.current = null;
    try {
      setReference(await extractReferenceStyle(picked, setReferenceProgress));
    } catch (err) {
      setReferenceError(err instanceof Error ? err.message : "Couldn't read that document.");
    } finally {
      setReferenceProgress(null);
    }
  }

  async function formattingTemplateId(): Promise<string | undefined> {
    if (!hasReference) return hasTemplate ? templateId! : undefined;
    if (!referenceTemplateId.current) {
      const created = await createTemplate({
        name: reference!.suggestedName,
        description: `The look of ${referenceFile!.name}.`,
        styleSystem: reference!.styleSystem,
      });
      referenceTemplateId.current = created.id;
    }
    return referenceTemplateId.current;
  }

  /** Shows a job's real progress on the processing screen; a step once reached stays reached. */
  function showProgress(title: string, steps: Processing["steps"]) {
    let reached = -1;
    return (current: JobProgress) => {
      const index = current.stage === "complete" ? steps.length : steps.findIndex((step) => step.stage === current.stage);
      reached = Math.max(reached, index);
      setProcessing({ title, steps, current, reached });
    };
  }

  async function handleFinish() {
    setError(null);
    const show = showProgress("Setting up your document", importSteps(startMethod, file));
    show({ stage: "queued", progress: 0 });
    try {
      const document = startMethod === "paste" ? await importText(text, undefined, show) : await importFile(file!, undefined, show);
      setProcessing(null);
      setReviewDocument(document);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Is the backend running on port 8000?");
      setProcessing(null);
    }
  }

  async function handleContinueFromReview() {
    if (!reviewDocument) return;
    setError(null);
    setReviewContinuing(true);
    try {
      if (effectiveFormattingChoice !== "later") {
        const instructions = effectiveFormattingChoice === "with-instructions" ? instructionsText.trim() || undefined : undefined;
        const show = showProgress("Formatting your document", formattingSteps(Boolean(instructions)));
        show({ stage: "queued", progress: 0 });
        // A brand-new document has no manual overrides yet, so this first
        // formatting call can never produce a conflict -- nothing to branch on.
        await formatDocument(reviewDocument.id, { templateId: await formattingTemplateId(), instructionsText: instructions, onProgress: show });
      }
      router.push(`/documents/${reviewDocument.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Is the backend running on port 8000?");
      setProcessing(null);
      setReviewContinuing(false);
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-6 px-6 py-16">
      {processing ? (
        <ProcessingScreen processing={processing} />
      ) : reviewDocument ? (
        <StructureReviewScreen document={reviewDocument} onContinue={handleContinueFromReview} continuing={reviewContinuing} error={error} />
      ) : (
        <>
      {step === 1 && (
        <div className="flex flex-col gap-4">
          <StepHeader step={1} title="What are you creating?" />
          <div className="flex flex-col gap-2">
            {templates.map((template) => (
              <RadioCard
                key={template.id}
                selected={!noTemplate && templateId === template.id}
                onSelect={() => {
                  setTemplateId(template.id);
                  setNoTemplate(false);
                  setUseReference(false);
                }}
                title={template.isDefault ? `${template.name} (default)` : template.name}
                description={template.description}
                preview={<TemplatePreviewSample styles={template.previewStyles} />}
              />
            ))}
            <RadioCard
              selected={useReference}
              onSelect={() => {
                setUseReference(true);
                setNoTemplate(false);
                setTemplateId(null);
              }}
              title="Match a reference document"
              description="Upload a Word document whose look you want: its fonts, spacing, headings and page setup are copied."
              icon={<FileSearch className="h-4 w-4 shrink-0" aria-hidden="true" />}
            />
            {useReference && (
              <div className="flex flex-col gap-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
                <input
                  type="file"
                  accept=".docx"
                  aria-label="Reference Word document"
                  onChange={(e) => {
                    const picked = e.target.files?.[0];
                    if (picked) void readReference(picked);
                  }}
                  className={`${inputClass} file:mr-4 file:rounded-full file:border-0 file:bg-accent file:px-4 file:py-2 file:text-sm file:font-medium file:text-accent-foreground`}
                />
                {referenceProgress && <JobProgressBar progress={referenceProgress} label={`Reading ${referenceFile?.name ?? "the document"}`} />}
                {referenceError && <p className="text-xs text-red-600 dark:text-red-400">{referenceError}</p>}
                {reference && <ReferenceStyleSummary reference={reference} />}
              </div>
            )}
            <RadioCard
              selected={noTemplate}
              onSelect={() => {
                setNoTemplate(true);
                setTemplateId(null);
                setUseReference(false);
              }}
              title="Something else"
              description="Skip templates for now -- format manually or decide later in the editor."
            />
          </div>
          <NavRow onNext={() => setStep(2)} nextLabel="Continue" nextDisabled={!noTemplate && !templateId && !hasReference} />
        </div>
      )}

      {step === 2 && (
        <div className="flex flex-col gap-4">
          <StepHeader step={2} title="How do you want to start?" />
          <div className="flex gap-2">
            <RadioCard selected={startMethod === "paste"} onSelect={() => setStartMethod("paste")} title="Paste text" icon={<ClipboardPaste className="h-4 w-4 shrink-0" aria-hidden="true" />} />
            <RadioCard selected={startMethod === "upload"} onSelect={() => setStartMethod("upload")} title="Upload a file" icon={<Upload className="h-4 w-4 shrink-0" aria-hidden="true" />} />
          </div>

          {startMethod === "paste" ? (
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={10}
              placeholder="Paste your raw text here..."
              className={`${inputClass} font-mono`}
            />
          ) : (
            <div className="flex flex-col gap-2">
              <input
                type="file"
                accept=".txt,.docx,.pdf"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className={`${inputClass} file:mr-4 file:rounded-full file:border-0 file:bg-accent file:px-4 file:py-2 file:text-sm file:font-medium file:text-accent-foreground`}
              />
              <p className="text-xs text-zinc-500">
                Accepts .txt, .docx, or .pdf{maxFileMb ? ` (up to ${maxFileMb} MB on your plan)` : ""}.
              </p>
            </div>
          )}
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Your words are never rewritten. Word files are read as they are; plain text without headings or lists of its own is read by the AI
            to find its structure.
          </p>

          <NavRow
            onBack={() => setStep(1)}
            onNext={() => setStep(3)}
            nextLabel="Continue"
            nextDisabled={startMethod === "paste" ? !text.trim() : !file}
          />
        </div>
      )}

      {step === 3 && (
        <div className="flex flex-col gap-4">
          <StepHeader step={3} title="How should it be formatted?" />
          <div className="flex flex-col gap-2">
            {hasFormattingSource && (
              <RadioCard
                selected={effectiveFormattingChoice === "template-only"}
                onSelect={() => setFormattingChoice("template-only")}
                title={hasReference ? "Apply the reference's look now" : "Apply the template now"}
                description={
                  hasReference
                    ? "Copies its look onto your document; your text stays as it is. It's also saved as a template you can reuse."
                    : "Formats immediately using this template's defaults."
                }
              />
            )}
            <RadioCard
              selected={effectiveFormattingChoice === "with-instructions"}
              onSelect={() => setFormattingChoice("with-instructions")}
              title={hasFormattingSource ? `${hasReference ? "Reference look" : "Template"} + AI instructions` : "AI instructions"}
              description={hasFormattingSource ? "Describe in plain language what else to change." : "Describe in plain language how it should be formatted."}
            />
            <RadioCard
              selected={effectiveFormattingChoice === "later"}
              onSelect={() => setFormattingChoice("later")}
              title="Decide later"
              description="Open the editor without applying any formatting yet."
            />
          </div>

          {effectiveFormattingChoice === "with-instructions" && (
            <textarea
              value={instructionsText}
              onChange={(e) => setInstructionsText(e.target.value)}
              rows={4}
              placeholder='e.g. "make headings bold and justify all paragraphs"'
              className={inputClass}
            />
          )}

          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          <NavRow onBack={() => setStep(2)} onNext={handleFinish} nextLabel="Create document" />
        </div>
      )}
        </>
      )}
    </main>
  );
}
