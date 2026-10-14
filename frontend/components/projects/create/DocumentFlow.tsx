"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState, useSyncExternalStore } from "react";

import { Notice } from "@/components/ui/Notice";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import { formatDocument, getDocument, importFile, importText } from "@/services/api";
import { useAiAvailability, useBilling, useTemplates } from "@/services/queries";
import type { Document, JobProgress, Template } from "@/types/document";

import { AddContent, type ContentDraft, type ContentInput } from "./AddContent";
import { ChooseLook, initialLook } from "./ChooseLook";
import { advance, formatStages, importStages, ProcessingView, type Processing, type ProcessingStage } from "./ProcessingView";
import { suggestLook } from "./recommendLook";
import { StructureReview } from "./StructureReview";

type Step = "content" | "structure" | "look";
const STEPS: Step[] = ["content", "structure", "look"];
const NO_TEMPLATES: Template[] = [];
/** Step 1's text, kept in this tab while the person moves back and forth or reloads. */
const DRAFT_KEY = "smartdoc:new-document:draft";

function parseDraft(raw: string | null, mode: string | null): ContentDraft {
  const fallback: ContentDraft = { method: mode === "upload" ? "upload" : "paste", text: "" };
  try {
    const saved = JSON.parse(raw ?? "null") as ContentDraft | null;
    return saved && typeof saved.text === "string" ? { ...saved, method: mode === "upload" ? "upload" : saved.method } : fallback;
  } catch {
    return fallback;
  }
}

function storedDraft(): string | null {
  try {
    return window.sessionStorage.getItem(DRAFT_KEY);
  } catch {
    return null;
  }
}

// Read once per render; nothing else in this tab writes it, so there is nothing to subscribe to.
const noSubscription = () => () => undefined;

function keepDraft(draft: ContentDraft | null) {
  try {
    if (draft) window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    else window.sessionStorage.removeItem(DRAFT_KEY);
  } catch {
    // Storage blocked (private window): the draft lives as long as the page.
  }
}

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
 * look -> the format job -> the editor. Built on the same APIs as the 1.x wizard. Each step is also in the
 * address (?step=&doc=), so the browser's Back and a reload land on the same step with nothing lost: once
 * imported, the document is saved (a draft), and step 1's text is kept in this tab.
 */
export function DocumentFlow() {
  const { m } = useI18n();
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const templates = useTemplates();
  const maxFileMb = useBilling().data?.plan.entitlements.maxDocumentSizeMb;
  const aiConfigured = useAiAvailability().data === true;

  const urlDoc = params.get("doc");
  const urlStep = params.get("step");
  const stepFromUrl: Step = urlDoc && (urlStep === "structure" || urlStep === "look") ? urlStep : "content";
  const [step, setStep] = useState<Step>(stepFromUrl);
  // The browser's Back and Forward change the address: the step follows it.
  const [seenUrl, setSeenUrl] = useState(`${urlStep}|${urlDoc}`);
  if (seenUrl !== `${urlStep}|${urlDoc}`) {
    setSeenUrl(`${urlStep}|${urlDoc}`);
    setStep(stepFromUrl);
  }

  // The kept text: read on the client only (the server has no session storage), so hydration matches.
  const storedRaw = useSyncExternalStore(noSubscription, storedDraft, () => null);
  const mode = params.get("mode");
  const stored = useMemo(() => parseDraft(storedRaw, mode), [storedRaw, mode]);
  const [edited, setEdited] = useState<ContentDraft | null>(null);
  const draft = edited ?? stored;
  const [processing, setProcessing] = useState<Processing | null>(null);
  const [formatting, setFormatting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The draft the content became: what this page made, else (after a reload) read again by its id.
  const [made, setMade] = useState<Document | null>(null);
  const loaded = useQuery({ queryKey: ["flow-document", urlDoc], queryFn: () => getDocument(urlDoc!), enabled: Boolean(urlDoc) && made?.id !== urlDoc });
  const document = made && (!urlDoc || made.id === urlDoc) ? made : (loaded.data ?? null);
  const suggestion = useMemo(() => (document ? suggestLook(document.elements, document.metadata.title, templates.data ?? NO_TEMPLATES) : null), [document, templates.data]);

  /** To a step, as a new entry in the browser's history (so Back returns to the step before). */
  function go(next: Step, documentId = document?.id) {
    const query = new URLSearchParams(params.toString());
    query.set("step", next);
    if (documentId) query.set("doc", documentId);
    setStep(next);
    router.push(`/new?${query}`, { scroll: true });
  }

  function updateDraft(next: ContentDraft) {
    setEdited(next);
    keepDraft(next);
  }

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
      setMade(imported);
      go("structure", imported.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : m.create.error);
    } finally {
      setProcessing(null);
    }
  }

  function confirmed(saved: Document) {
    setMade(saved);
    queryClient.setQueryData(["flow-document", saved.id], saved);
    go("look", saved.id);
  }

  async function applyLook(look: { templateId?: string; instructions?: string }) {
    if (!document) return;
    setError(null);
    setFormatting(true);
    const show = follow("formatTitle", formatStages(Boolean(look.instructions)));
    try {
      // A new document has no manual overrides yet, so this first formatting can't conflict with any.
      await formatDocument(document.id, { templateId: look.templateId, instructionsText: look.instructions, onProgress: show });
      keepDraft(null);
      router.push(`/documents/${document.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : m.create.error);
      setProcessing(null);
      setFormatting(false);
    }
  }

  function openUnformatted() {
    if (!document) return;
    keepDraft(null);
    router.push(`/documents/${document.id}`);
  }

  const titles = { content: m.create.content, structure: m.create.structure, look: m.create.look };
  const heading = titles[step];
  const waitingForDocument = step !== "content" && !document;

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-4 py-5 sm:gap-6 sm:px-6 sm:py-10">
      {processing ? (
        <ProcessingView processing={processing} />
      ) : (
        <>
          <Stepper step={step} />
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-accent">{format(m.create.stepOf, { step: STEPS.indexOf(step) + 1 })}</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{heading.title}</h1>
            <p className="mt-1 text-sm text-muted sm:mt-1.5">{heading.subtitle}</p>
          </div>
          {error && <Notice tone="error">{error}</Notice>}
          {loaded.error && step !== "content" && <Notice tone="error">{loaded.error.message}</Notice>}
          {waitingForDocument && !loaded.error && (
            <p className="flex items-center gap-2 text-sm text-muted">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {m.flow.loadingDocument}
            </p>
          )}
          {step === "content" && (
            <AddContent
              draft={draft}
              onDraft={updateDraft}
              maxFileMb={maxFileMb}
              analysed={document ? { title: document.metadata.title } : null}
              onContinue={() => go("structure")}
              onSubmit={addContent}
            />
          )}
          {step === "structure" && document && (
            // A tracked-changes choice reads the document again: the review starts over from what it now is.
            <StructureReview key={document.revision} document={document} onDocument={setMade} onConfirmed={confirmed} onBack={() => go("content")} />
          )}
          {step === "look" && document && !templates.isPending && (
            <ChooseLook
              templates={templates.data ?? NO_TEMPLATES}
              initial={initialLook(templates.data ?? NO_TEMPLATES, params.get("template"), params.get("reference") === "1", suggestion?.templateId)}
              suggestion={suggestion}
              aiConfigured={aiConfigured}
              onApply={applyLook}
              onSkip={openUnformatted}
              onBack={() => go("structure")}
              busy={formatting}
            />
          )}
        </>
      )}
    </main>
  );
}
