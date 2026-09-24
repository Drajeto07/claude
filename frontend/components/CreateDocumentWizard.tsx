"use client";

import { CheckCircle2, Circle, ClipboardPaste, Loader2, Upload } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { StructurePanel } from "@/components/StructurePanel";
import { TemplatePreviewSample } from "@/components/TemplatePreviewSample";
import { createDocument, formatDocument, listTemplates, uploadDocument } from "@/services/api";
import type { Document, Template } from "@/types/document";

type Step = 1 | 2 | 3;
type StartMethod = "paste" | "upload";
type FormattingChoice = "template-only" | "with-instructions" | "later";
type ProcessingStage = "reading" | "formatting" | "done";

const PROCESSING_LABELS: Record<Exclude<ProcessingStage, "done">, string> = {
  reading: "Reading & analyzing your content",
  formatting: "Applying formatting",
};

/**
 * Mirrors the two real network calls handleFinish actually makes (create/
 * upload, then optionally format) -- never a fake timer. "formatting" is
 * simply left out of the list when the user chose "Decide later", rather
 * than shown as a step that magically completes with nothing behind it.
 */
function ProcessingScreen({ stage, willFormat }: { stage: ProcessingStage; willFormat: boolean }) {
  const order: ProcessingStage[] = willFormat ? ["reading", "formatting", "done"] : ["reading", "done"];
  const currentIndex = order.indexOf(stage);
  const visibleStages = (Object.keys(PROCESSING_LABELS) as Exclude<ProcessingStage, "done">[]).filter((key) => willFormat || key !== "formatting");

  return (
    <div className="flex flex-col gap-6 py-12">
      <h1 className="text-center text-2xl font-semibold text-zinc-900 dark:text-zinc-50">Setting up your document</h1>
      <div className="mx-auto flex flex-col gap-3">
        {visibleStages.map((key) => {
          const done = order.indexOf(key) < currentIndex;
          const active = key === stage;
          return (
            <div key={key} className="flex items-center gap-3 text-sm">
              {done ? (
                <CheckCircle2 className="h-5 w-5 shrink-0 text-accent" aria-hidden="true" />
              ) : active ? (
                <Loader2 className="h-5 w-5 shrink-0 animate-spin text-accent" aria-hidden="true" />
              ) : (
                <Circle className="h-5 w-5 shrink-0 text-zinc-300 dark:text-zinc-700" aria-hidden="true" />
              )}
              <span className={done || active ? "text-zinc-900 dark:text-zinc-50" : "text-zinc-400 dark:text-zinc-600"}>{PROCESSING_LABELS[key]}</span>
            </div>
          );
        })}
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
 * Progressive 3-step version of the creation screen (doc type -> start
 * method -> formatting method -> one final Continue), replacing the old
 * flat paste/upload tab pair. Reuses the exact same backend calls the old
 * PasteTextForm/FileUploadForm made (createDocument/uploadDocument), plus
 * formatDocument -- new layout and sequencing only, no new endpoints.
 */
export function CreateDocumentWizard() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [step, setStep] = useState<Step>(1);

  const [templates, setTemplates] = useState<Template[]>([]);
  const [pickedTemplateId, setTemplateId] = useState<string | null>(null);
  const [noTemplate, setNoTemplate] = useState(false);
  // The workspace's default template is preselected until something else is picked.
  const defaultTemplateId = templates.find((template) => template.isDefault)?.id ?? null;
  const templateId = noTemplate ? null : (pickedTemplateId ?? defaultTemplateId);
  const hasTemplate = Boolean(templateId);

  const [startMethod, setStartMethod] = useState<StartMethod>(searchParams.get("mode") === "upload" ? "upload" : "paste");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const [formattingChoice, setFormattingChoice] = useState<FormattingChoice>("template-only");
  const [instructionsText, setInstructionsText] = useState("");

  const [processing, setProcessing] = useState<ProcessingStage | null>(null);
  const [reviewDocument, setReviewDocument] = useState<Document | null>(null);
  const [reviewContinuing, setReviewContinuing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, []);

  // Derived rather than synced via an effect, so going back and dropping the
  // template falls back to "with-instructions" without an extra render pass,
  // and re-picking a template naturally restores the original raw choice.
  const effectiveFormattingChoice: FormattingChoice = !hasTemplate && formattingChoice === "template-only" ? "with-instructions" : formattingChoice;

  async function handleFinish() {
    setError(null);
    setProcessing("reading");
    try {
      const document = startMethod === "paste" ? await createDocument(text) : await uploadDocument(file!);
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
        setProcessing("formatting");
        // A brand-new document has no manual overrides yet, so this first
        // formatting call can never produce a conflict -- nothing to branch on.
        await formatDocument(reviewDocument.id, {
          templateId: hasTemplate ? templateId! : undefined,
          instructionsText: effectiveFormattingChoice === "with-instructions" ? instructionsText.trim() || undefined : undefined,
        });
        setProcessing("done");
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
        <ProcessingScreen stage={processing} willFormat={effectiveFormattingChoice !== "later"} />
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
                }}
                title={template.isDefault ? `${template.name} (default)` : template.name}
                description={template.description}
                preview={<TemplatePreviewSample styles={template.previewStyles} />}
              />
            ))}
            <RadioCard
              selected={noTemplate}
              onSelect={() => {
                setNoTemplate(true);
                setTemplateId(null);
              }}
              title="Something else"
              description="Skip templates for now -- format manually or decide later in the editor."
            />
          </div>
          <NavRow onNext={() => setStep(2)} nextLabel="Continue" nextDisabled={!noTemplate && !templateId} />
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
              <p className="text-xs text-zinc-500">Accepts .txt, .docx, or .pdf (up to 10MB).</p>
            </div>
          )}

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
            {hasTemplate && (
              <RadioCard
                selected={effectiveFormattingChoice === "template-only"}
                onSelect={() => setFormattingChoice("template-only")}
                title="Apply the template now"
                description="Formats immediately using this template's defaults."
              />
            )}
            <RadioCard
              selected={effectiveFormattingChoice === "with-instructions"}
              onSelect={() => setFormattingChoice("with-instructions")}
              title={hasTemplate ? "Template + AI instructions" : "AI instructions"}
              description={hasTemplate ? "Describe in plain language what else to change." : "Describe in plain language how it should be formatted."}
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
