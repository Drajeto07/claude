"use client";

import { CheckCircle2, ExternalLink, FileUp, Loader2, Save } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";

import { ReferenceStyleSummary } from "@/components/ReferenceStyleSummary";
import { TemplatePreviewSample } from "@/components/TemplatePreviewSample";
import type { FormattingState } from "@/editor/useFormattingState";
import { createTemplate, extractReferenceStyle } from "@/services/api";
import type { CreatedTemplate, ReferenceStyle } from "@/types/document";

/**
 * Format by Example (корекции.docx §17): upload a Word document whose look you
 * want, review what was read from it, then apply it. Applying saves it as a
 * template first, so it re-applies, edits and reuses like any other.
 */
function MatchReference({ state }: { state: FormattingState }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [reference, setReference] = useState<ReferenceStyle | null>(null);
  const [busy, setBusy] = useState<"reading" | "applying" | "saving" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<CreatedTemplate | null>(null);

  async function read(picked: File) {
    setFile(picked);
    setReference(null);
    setSaved(null);
    setError(null);
    setBusy("reading");
    try {
      setReference(await extractReferenceStyle(picked));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't read that document.");
    } finally {
      setBusy(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function keep(apply: boolean) {
    if (!reference || !file) return;
    setBusy(apply ? "applying" : "saving");
    setError(null);
    try {
      const created = await createTemplate({
        name: reference.suggestedName,
        description: `The look of ${file.name}.`,
        styleSystem: reference.styleSystem,
      });
      if (apply) await state.applyTemplate(created.id);
      else await state.refreshTemplates();
      setSaved(created);
      setReference(null);
      setFile(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save the style.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-dashed border-zinc-300 p-3 dark:border-zinc-700">
      <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Match another document</p>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Upload a Word document whose look you want. Its fonts, sizes, spacing, headings and page setup are copied; your text
        stays as it is.
      </p>
      <input
        ref={inputRef}
        type="file"
        accept=".docx"
        className="sr-only"
        aria-label="Reference Word document"
        onChange={(event) => {
          const picked = event.target.files?.[0];
          if (picked) void read(picked);
        }}
      />
      <button
        type="button"
        disabled={busy !== null}
        onClick={() => inputRef.current?.click()}
        className="flex items-center gap-1.5 self-start rounded-full border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 hover:border-accent hover:text-accent disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300"
      >
        {busy === "reading" ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <FileUp className="h-3.5 w-3.5" aria-hidden="true" />}
        {busy === "reading" ? `Reading ${file?.name ?? "the document"}…` : reference ? "Choose another document" : "Choose a .docx file"}
      </button>
      {reference && file && (
        <>
          <p className="text-xs text-zinc-600 dark:text-zinc-400">
            The look of <span className="font-medium">{file.name}</span>:
          </p>
          <ReferenceStyleSummary reference={reference} />
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void keep(true)}
              className="rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50"
            >
              {busy === "applying" ? "Applying…" : "Apply to this document"}
            </button>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void keep(false)}
              className="text-sm font-medium text-zinc-600 hover:text-accent disabled:opacity-50 dark:text-zinc-400"
            >
              {busy === "saving" ? "Saving…" : "Only save as a template"}
            </button>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => {
                setReference(null);
                setFile(null);
              }}
              className="text-sm text-zinc-500 hover:text-accent disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </>
      )}
      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
      {saved && (
        <p className="text-xs text-green-700 dark:text-green-400">
          Saved as the template &ldquo;{saved.name}&rdquo;.{" "}
          <a href={`/templates/${saved.id}`} target="_blank" rel="noopener" className="font-medium underline">
            Adjust it
          </a>
        </p>
      )}
    </div>
  );
}

/**
 * The "Шаблони" rail panel: pick a template to apply, open the template
 * library, or save this document's current look as a new template. Shares its
 * templateId/instructionsText state with InstructionsPanel via the
 * useFormattingState hook (called once in DocumentEditor) so applying a
 * template here never silently drops instructions typed in the other
 * panel, and vice versa (see useFormattingState.ts's own doc comment).
 */
export function TemplatesPanel({ state, documentId, documentTitle }: { state: FormattingState; documentId: string; documentTitle: string }) {
  const { templates, refreshTemplates, templateId, setTemplateId, isApplying, error, notice, handleApply } = state;
  const [draftName, setDraftName] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<CreatedTemplate | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function saveAsTemplate(event: FormEvent) {
    event.preventDefault();
    const name = draftName?.trim();
    if (!name) return;
    setSaving(true);
    setSaveError(null);
    try {
      const created = await createTemplate({ name, sourceDocumentId: documentId });
      setSaved(created);
      setDraftName(null);
      await refreshTemplates();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Could not save the template.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        Choose a template. Applying it keeps any instructions already entered in the Instructions panel.
      </p>
      <a
        href="/templates"
        target="_blank"
        rel="noopener"
        className="inline-flex items-center gap-1 self-start text-xs font-medium text-accent hover:underline"
      >
        Manage templates
        <ExternalLink className="h-3 w-3" aria-hidden="true" />
        <span className="sr-only">(opens in a new tab)</span>
      </a>
      <MatchReference state={state} />
      <div className="flex flex-col gap-2">
        <button
          type="button"
          onClick={() => setTemplateId("")}
          className={`flex items-center justify-between rounded-lg border px-3 py-2.5 text-left text-sm transition-colors ${
            templateId === ""
              ? "border-accent bg-accent/5 text-zinc-900 dark:text-zinc-50"
              : "border-zinc-200 text-zinc-600 hover:border-zinc-300 dark:border-zinc-800 dark:text-zinc-400"
          }`}
        >
          No template
          {templateId === "" && <CheckCircle2 className="h-4 w-4 text-accent" aria-hidden="true" />}
        </button>
        {templates.map((template) => (
          <button
            key={template.id}
            type="button"
            onClick={() => setTemplateId(template.id)}
            aria-pressed={templateId === template.id}
            className={`rounded-lg border px-3 py-2.5 text-left text-sm transition-colors ${
              templateId === template.id
                ? "border-accent bg-accent/5 text-zinc-900 dark:text-zinc-50"
                : "border-zinc-200 text-zinc-600 hover:border-zinc-300 dark:border-zinc-800 dark:text-zinc-400"
            }`}
          >
            <span className="flex items-center justify-between gap-2">
              <span className="min-w-0">
                <span className="flex items-center gap-2 font-medium">
                  <span className="truncate">{template.name}</span>
                  {template.isDefault && <span className="shrink-0 rounded-full bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">Default</span>}
                  {!template.builtin && <span className="shrink-0 text-[10px] font-normal text-zinc-400">Yours</span>}
                </span>
                {template.description && <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">{template.description}</span>}
              </span>
              {templateId === template.id && <CheckCircle2 className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />}
            </span>
            <TemplatePreviewSample styles={template.previewStyles} className="h-24" />
          </button>
        ))}
      </div>
      <button
        type="button"
        onClick={() => handleApply()}
        disabled={isApplying}
        className="rounded-full bg-accent px-6 py-2.5 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isApplying ? "Applying..." : "Apply formatting"}
      </button>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {notice && (
        <p className={`text-sm ${notice.kind === "success" ? "text-green-700 dark:text-green-400" : "text-amber-700 dark:text-amber-400"}`}>
          {notice.text}
        </p>
      )}

      <div className="mt-2 border-t border-zinc-200 pt-4 dark:border-zinc-800">
        {draftName === null ? (
          <button
            type="button"
            onClick={() => {
              setSaved(null);
              setDraftName(`${documentTitle} style`);
            }}
            className="flex items-center gap-1.5 text-sm font-medium text-zinc-700 hover:text-accent dark:text-zinc-300"
          >
            <Save className="h-4 w-4" aria-hidden="true" />
            Save this document&rsquo;s look as a template
          </button>
        ) : (
          <form onSubmit={saveAsTemplate} className="flex flex-col gap-2">
            <label className="flex flex-col gap-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
              Template name
              <input
                autoFocus
                value={draftName}
                maxLength={255}
                onChange={(event) => setDraftName(event.target.value)}
                className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 focus:border-accent focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
              />
            </label>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              Saves the page setup and the style of each kind of text. Changes made to a single paragraph aren&rsquo;t included.
            </p>
            <div className="flex items-center gap-3">
              <button
                type="submit"
                disabled={saving || !draftName.trim()}
                className="rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50"
              >
                {saving ? "Saving..." : "Save template"}
              </button>
              <button type="button" onClick={() => setDraftName(null)} className="text-sm text-zinc-500 hover:text-accent">
                Cancel
              </button>
            </div>
          </form>
        )}
        {saveError && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{saveError}</p>}
        {saved && (
          <div className="mt-2 text-sm text-green-700 dark:text-green-400">
            Saved as &ldquo;{saved.name}&rdquo;.{" "}
            <a href={`/templates/${saved.id}`} target="_blank" rel="noopener" className="font-medium underline">
              Edit it
            </a>
            {saved.notes.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-xs text-amber-700 dark:text-amber-400">
                {saved.notes.map((note) => (
                  <li key={note}>Not carried over: {note}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
