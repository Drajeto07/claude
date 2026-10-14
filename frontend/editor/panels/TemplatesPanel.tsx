"use client";

import { CheckCircle2, ExternalLink, FileUp, Save } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";

import { JobProgressBar } from "@/components/JobProgressBar";
import { ReferenceStyleSummary } from "@/components/ReferenceStyleSummary";
import { TemplatePreviewSample } from "@/components/TemplatePreviewSample";
import { useDocumentEditor } from "@/editor/EditorState";
import type { FormattingState } from "@/editor/useFormatting";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import { createTemplate, extractReferenceStyle, previewStyle } from "@/services/api";
import type { CreatedTemplate, DocumentStylePreview, JobProgress, ReferenceStyle } from "@/types/document";

/** This document now and with the reference's look, side by side, and what changes (FMT-003). */
function BeforeAfter({ preview }: { preview: DocumentStylePreview }) {
  const t = useI18n().m.edPanels.templates;
  const shown = preview.changes.slice(0, 8);
  return (
    <section aria-label={t.beforeAfter} className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted">{t.now}</p>
          <TemplatePreviewSample styles={preview.before} className="h-24" />
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted">{t.withLook}</p>
          <TemplatePreviewSample styles={preview.after} className="h-24" />
        </div>
      </div>
      {preview.changes.length === 0 ? (
        <p className="text-xs text-muted">{t.alreadyLooks}</p>
      ) : (
        <ul className="list-disc pl-4 text-xs text-muted">
          {shown.map((change) => (
            <li key={change}>{change}</li>
          ))}
          {preview.changes.length > shown.length && <li>{format(t.more, { count: preview.changes.length - shown.length })}</li>}
        </ul>
      )}
    </section>
  );
}

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
  const [readProgress, setReadProgress] = useState<JobProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<CreatedTemplate | null>(null);
  const [preview, setPreview] = useState<DocumentStylePreview | null>(null);
  const { document } = useDocumentEditor();
  const { m } = useI18n();
  const t = m.edPanels.templates;

  async function read(picked: File) {
    setFile(picked);
    setReference(null);
    setPreview(null);
    setSaved(null);
    setError(null);
    setBusy("reading");
    try {
      const found = await extractReferenceStyle(picked, setReadProgress);
      setReference(found);
      // Tried on this document before anything is saved: what it would change.
      setPreview(await previewStyle(document.id, found.styleSystem).catch(() => null));
    } catch (err) {
      setError(err instanceof Error ? err.message : t.readFailed);
    } finally {
      setBusy(null);
      setReadProgress(null);
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
        description: format(t.lookOfFile, { name: file.name }),
        styleSystem: reference.styleSystem,
      });
      if (apply) await state.applyTemplate(created.id);
      else await state.refreshTemplates();
      setSaved(created);
      setReference(null);
      setFile(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.styleFailed);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-dashed border-line-strong p-3">
      <p className="text-sm font-medium text-foreground">{t.matchTitle}</p>
      <p className="text-xs text-muted">{t.matchIntro}</p>
      <input
        ref={inputRef}
        type="file"
        accept=".docx"
        className="sr-only"
        aria-label={t.reference}
        onChange={(event) => {
          const picked = event.target.files?.[0];
          if (picked) void read(picked);
        }}
      />
      <button
        type="button"
        disabled={busy !== null || state.isApplying}
        onClick={() => inputRef.current?.click()}
        className="flex items-center gap-1.5 self-start rounded-full border border-line-strong px-3 py-1.5 text-xs font-medium text-foreground hover:border-accent hover:text-accent disabled:opacity-50"
      >
        <FileUp className="h-3.5 w-3.5" aria-hidden="true" />
        {reference ? t.chooseAnother : t.choose}
      </button>
      {busy === "reading" && readProgress && <JobProgressBar progress={readProgress} label={format(t.reading, { name: file?.name ?? t.theDocument })} />}
      {reference && file && (
        <>
          <p className="text-xs text-muted">
            {t.lookOf} <span className="font-medium">{file.name}</span>:
          </p>
          <ReferenceStyleSummary reference={reference} />
          {preview && <BeforeAfter preview={preview} />}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy !== null || state.isApplying}
              onClick={() => void keep(true)}
              className="rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50"
            >
              {busy === "applying" ? t.applyingNow : t.applyHere}
            </button>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void keep(false)}
              className="text-sm font-medium text-muted hover:text-accent disabled:opacity-50"
            >
              {busy === "saving" ? t.savingNow : t.onlySave}
            </button>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => {
                setReference(null);
                setFile(null);
              }}
              className="text-sm text-muted hover:text-accent disabled:opacity-50"
            >
              {m.edPanels.common.cancel}
            </button>
          </div>
          {state.applyingFrom === "reference" && state.progress && <JobProgressBar progress={state.progress} />}
        </>
      )}
      {error && <p className="text-xs text-danger">{error}</p>}
      {saved && (
        <p className="text-xs text-success">
          {format(t.savedTemplate, { name: saved.name })}{" "}
          <a href={`/templates/${saved.id}`} target="_blank" rel="noopener" className="font-medium underline">
            {t.adjust}
          </a>
        </p>
      )}
    </div>
  );
}

/**
 * The Templates rail panel: pick a template to apply, open the template
 * library, or save this document's current look as a new template. Shares its
 * templateId/instructionsText state with InstructionsPanel (useFormatting,
 * called once in the editor shell) so applying a template here never silently
 * drops instructions typed in the other panel, and vice versa.
 */
export function TemplatesPanel({ state }: { state: FormattingState }) {
  const { document } = useDocumentEditor();
  const documentId = document.id;
  const documentTitle = document.metadata.title;
  const { m } = useI18n();
  const t = m.edPanels.templates;
  const { templates, refreshTemplates, templateId, setTemplateId, isApplying, applyingFrom, progress, error, notice, handleApply } = state;
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
      setSaveError(err instanceof Error ? err.message : t.saveFailed);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">{t.intro}</p>
      <a
        href="/templates"
        target="_blank"
        rel="noopener"
        className="inline-flex items-center gap-1 self-start text-xs font-medium text-accent hover:underline"
      >
        {t.manage}
        <ExternalLink className="h-3 w-3" aria-hidden="true" />
        <span className="sr-only">{m.edPanels.common.newTab}</span>
      </a>
      <MatchReference state={state} />
      <div className="flex flex-col gap-2">
        <button
          type="button"
          onClick={() => setTemplateId("")}
          className={`flex items-center justify-between rounded-lg border px-3 py-2.5 text-left text-sm transition-colors ${
            templateId === ""
              ? "border-accent bg-accent/5 text-foreground"
              : "border-line text-muted hover:border-line-strong"
          }`}
        >
          {t.none}
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
                ? "border-accent bg-accent/5 text-foreground"
                : "border-line text-muted hover:border-line-strong"
            }`}
          >
            <span className="flex items-center justify-between gap-2">
              <span className="min-w-0">
                <span className="flex items-center gap-2 font-medium">
                  <span className="truncate">{template.name}</span>
                  {template.isDefault && <span className="shrink-0 rounded-full bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">{t.default}</span>}
                  {!template.builtin && <span className="shrink-0 text-[10px] font-normal text-muted">{t.yours}</span>}
                </span>
                {template.description && <span className="mt-0.5 block text-xs text-muted">{template.description}</span>}
              </span>
              {templateId === template.id && <CheckCircle2 className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />}
            </span>
            <TemplatePreviewSample styles={template.previewStyles} className="h-24" />
          </button>
        ))}
      </div>
      <button
        type="button"
        onClick={() => handleApply("templates")}
        disabled={isApplying}
        className="rounded-full bg-accent px-6 py-2.5 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isApplying ? m.edPanels.common.applying : t.apply}
      </button>
      {applyingFrom === "templates" && progress && <JobProgressBar progress={progress} />}
      {error && <p className="text-sm text-danger">{error}</p>}
      {notice && (
        <p className={`text-sm ${notice.kind === "success" ? "text-success" : "text-warning"}`}>
          {notice.text}
        </p>
      )}

      <div className="mt-2 border-t border-line pt-4">
        {draftName === null ? (
          <button
            type="button"
            onClick={() => {
              setSaved(null);
              setDraftName(format(t.lookName, { title: documentTitle }));
            }}
            className="flex items-center gap-1.5 text-sm font-medium text-foreground hover:text-accent"
          >
            <Save className="h-4 w-4" aria-hidden="true" />
            {t.saveLook}
          </button>
        ) : (
          <form onSubmit={saveAsTemplate} className="flex flex-col gap-2">
            <label className="flex flex-col gap-1 text-xs font-medium text-muted">
              {t.name}
              <input
                autoFocus
                value={draftName}
                maxLength={255}
                onChange={(event) => setDraftName(event.target.value)}
                className="rounded-md border border-line-strong bg-surface px-2 py-1.5 text-sm text-foreground focus:border-accent focus:outline-none"
              />
            </label>
            <p className="text-xs text-muted">{t.saveNote}</p>
            <div className="flex items-center gap-3">
              <button
                type="submit"
                disabled={saving || !draftName.trim()}
                className="rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50"
              >
                {saving ? m.edPanels.common.saving : t.save}
              </button>
              <button type="button" onClick={() => setDraftName(null)} className="text-sm text-muted hover:text-accent">
                {m.edPanels.common.cancel}
              </button>
            </div>
          </form>
        )}
        {saveError && <p className="mt-2 text-sm text-danger">{saveError}</p>}
        {saved && (
          <div className="mt-2 text-sm text-success">
            {format(t.savedAs, { name: saved.name })}{" "}
            <a href={`/templates/${saved.id}`} target="_blank" rel="noopener" className="font-medium underline">
              {t.editIt}
            </a>
            {saved.notes.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-xs text-warning">
                {saved.notes.map((note) => (
                  <li key={note}>{format(t.notCarried, { note })}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
