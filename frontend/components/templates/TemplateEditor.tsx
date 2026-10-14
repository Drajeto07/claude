"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Copy, Loader2, Star, Trash2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { StylePreviewPage } from "@/components/templates/StylePreviewPage";
import { StyleSystemForm } from "@/components/templates/StyleSystemForm";
import { TemplateHistory } from "@/components/templates/TemplateHistory";
import { TEMPLATE_CATEGORIES, categoryLabel } from "@/components/templates/categories";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { fieldClasses } from "@/components/ui/TextField";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import { useDebouncedValue } from "@/lib/useDebouncedValue";
import { deleteTemplate, duplicateTemplate, errorMessage, restoreTemplateVersion, setDefaultTemplate, TemplateConflictError, updateTemplate } from "@/services/api";
import { useInvalidateTemplates, useStylePreview, useTemplate, useTemplateVersions } from "@/services/queries";
import type { StyleSystem, Template } from "@/types/document";

type Draft = { name: string; category: string; description: string; styleSystem: StyleSystem };

function toDraft(template: Template): Draft {
  return { name: template.name, category: template.category, description: template.description, styleSystem: template.styleSystem };
}

const PREVIEW_DEBOUNCE_MS = 300;

const inputClass = `${fieldClasses} h-10 disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-muted`;
const labelClass = "flex flex-col gap-1 text-xs font-medium text-muted";
const pillBase = "flex items-center gap-1.5 rounded-full border border-line-strong px-3 py-1.5 text-xs font-medium text-foreground transition-colors disabled:opacity-50";
const pillButton = `${pillBase} hover:border-accent hover:text-accent`;
const dangerPillButton = `${pillBase} hover:border-danger hover:text-danger`;

/**
 * View and edit one template: name and description, every part of its style
 * system, a live page preview resolved by the backend engine, its saved
 * versions, and default/duplicate/delete. Built-ins open read-only. The saved
 * template is server state (the query cache); only unsaved edits live here.
 */
export function TemplateEditor({ templateId }: { templateId: string }) {
  const { m } = useI18n();
  const t = m.templateEditor;
  const message = (error: unknown) => errorMessage(error, t.somethingWrong);
  const router = useRouter();
  const templateQuery = useTemplate(templateId);
  const template = templateQuery.data ?? null;
  const { data: versions = [] } = useTemplateVersions(templateId, Boolean(template && !template.builtin));
  const invalidateTemplates = useInvalidateTemplates();
  // Unsaved edits; null = showing the saved template as it is.
  const [edits, setDraft] = useState<Draft | null>(null);
  const draft = edits ?? (template ? toDraft(template) : null);
  const [error, setError] = useState<string | null>(null);
  const [savedNotice, setSavedNotice] = useState(false);
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  // Live preview: the unsaved style system, resolved by the real engine.
  const styleKey = draft ? JSON.stringify(draft.styleSystem) : null;
  const previewKey = useDebouncedValue(styleKey, PREVIEW_DEBOUNCE_MS);
  const previewQuery = useStylePreview(previewKey ? (JSON.parse(previewKey) as StyleSystem) : null, previewKey);
  const preview = previewQuery.data ?? null;
  const previewError = previewQuery.error ? message(previewQuery.error) : null;

  const dirty = Boolean(template && edits && JSON.stringify(toDraft(template)) !== JSON.stringify(edits));

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setSavedNotice(false);
    try {
      await action();
    } catch (reason) {
      if (reason instanceof TemplateConflictError) setConflict(true);
      else setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  const save = (overwrite = false) =>
    run(async () => {
      if (!template || !draft) return;
      const saved = await updateTemplate(template.id, overwrite ? null : template.version, {
        name: draft.name,
        category: draft.category,
        description: draft.description,
        styleSystem: draft.styleSystem,
      });
      await invalidateTemplates(saved);
      setDraft(null);
      setConflict(false);
      setSavedNotice(true);
    });

  const restore = (number: number) =>
    run(async () => {
      if (!template) return;
      if (dirty && !window.confirm(t.restoreUnsaved)) return;
      await invalidateTemplates(await restoreTemplateVersion(template.id, number, template.version));
      setDraft(null);
      setSavedNotice(true);
    });

  const loadLatest = () =>
    run(async () => {
      await templateQuery.refetch();
      setDraft(null);
      setConflict(false);
    });

  const toggleDefault = () =>
    run(async () => {
      if (!template) return;
      await setDefaultTemplate(template.isDefault ? null : template.id);
      await invalidateTemplates();
    });

  const duplicate = () =>
    run(async () => {
      if (!template) return;
      const copy = await duplicateTemplate(template.id);
      await invalidateTemplates();
      router.push(`/templates/${copy.id}`);
    });

  const remove = () =>
    run(async () => {
      if (!template) return;
      await deleteTemplate(template.id);
      await invalidateTemplates();
      router.push("/templates");
    });

  if (templateQuery.error) {
    return (
      <Shell>
        <Notice tone="error">{message(templateQuery.error)}</Notice>
      </Shell>
    );
  }
  if (!template || !draft) {
    return (
      <Shell>
        <p className="flex items-center gap-2 text-sm text-muted">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {t.loading}
        </p>
      </Shell>
    );
  }

  const categories: string[] = TEMPLATE_CATEGORIES.includes(draft.category as (typeof TEMPLATE_CATEGORIES)[number]) ? [...TEMPLATE_CATEGORIES] : [...TEMPLATE_CATEGORIES, draft.category];

  return (
    <Shell
      backLink={
        <Link
          href="/templates"
          onClick={(event) => {
            if (dirty && !window.confirm(t.leaveUnsaved)) event.preventDefault();
          }}
          className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-accent"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" /> {t.allTemplates}
        </Link>
      }
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight text-foreground">{template.name}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
            <span>{template.builtin ? t.builtinTemplate : format(t.version, { version: template.version ?? "" })}</span>
            <span>· {categoryLabel(template.category, m)}</span>
            {template.isDefault && <span className="rounded-full bg-accent-soft px-2 py-0.5 font-medium text-accent">{t.workspaceDefault}</span>}
            {template.sourceDocumentId && (
              <Link href={`/documents/${template.sourceDocumentId}`} className="text-accent hover:underline">
                {t.savedFromDocument}
              </Link>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={toggleDefault} disabled={busy} className={pillButton}>
            <Star className={`h-3.5 w-3.5 ${template.isDefault ? "fill-accent text-accent" : ""}`} aria-hidden="true" />
            {template.isDefault ? t.defaultForNew : t.useForNew}
          </button>
          <button type="button" onClick={duplicate} disabled={busy} className={pillButton}>
            <Copy className="h-3.5 w-3.5" aria-hidden="true" /> {t.duplicate}
          </button>
          {template.editable &&
            (confirmingDelete ? (
              <span className="flex items-center gap-2 text-xs text-muted">
                {t.deleteAsk}
                <button type="button" onClick={remove} disabled={busy} className="rounded-full bg-danger px-3 py-1.5 font-medium text-white hover:brightness-110">
                  {t.delete}
                </button>
                <button type="button" onClick={() => setConfirmingDelete(false)} className="font-medium hover:text-accent">
                  {t.cancel}
                </button>
              </span>
            ) : (
              <button type="button" onClick={() => setConfirmingDelete(true)} disabled={busy} className={dangerPillButton}>
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> {t.delete}
              </button>
            ))}
        </div>
      </div>

      {!template.editable && (
        <p className="mt-4 rounded-2xl border border-line bg-surface-muted px-4 py-3 text-sm text-muted">
          {template.builtin ? t.builtinReadOnly : t.notYours} {t.duplicateToOwn}
        </p>
      )}

      {conflict && (
        <div role="alert" className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl border border-warning/40 bg-warning-soft px-4 py-3 text-sm text-foreground">
          <span className="flex-1">{t.conflict}</span>
          <button type="button" onClick={loadLatest} className="font-medium underline">
            {t.loadLatest}
          </button>
          <button type="button" onClick={() => save(true)} className="font-medium underline">
            {t.saveMine}
          </button>
        </div>
      )}
      {error && (
        <div className="mt-4">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
        <fieldset disabled={!template.editable || busy} className="order-2 flex min-w-0 flex-col gap-3 lg:order-none">
          <legend className="sr-only">{t.settings}</legend>
          <section className="grid gap-3 rounded-2xl border border-line bg-surface p-4 sm:grid-cols-2">
            <label className={labelClass}>
              {t.name}
              <input className={inputClass} value={draft.name} maxLength={255} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
            </label>
            <label className={labelClass}>
              {t.category}
              <select className={inputClass} value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.target.value })}>
                {categories.map((category) => (
                  <option key={category} value={category}>
                    {categoryLabel(category, m)}
                  </option>
                ))}
              </select>
            </label>
            <label className={`${labelClass} sm:col-span-2`}>
              {t.description}
              <textarea className={`${inputClass} h-auto min-h-[4.5rem] py-2`} value={draft.description} maxLength={2000} onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
            </label>
          </section>
          <StyleSystemForm value={draft.styleSystem} onChange={(styleSystem) => setDraft({ ...draft, styleSystem })} />
        </fieldset>

        {/* One sticky column on wide screens; on narrow ones "contents" lets the
            preview go above the form and the history below it. */}
        <div className="contents lg:sticky lg:top-6 lg:flex lg:min-w-0 lg:flex-col lg:gap-4 lg:self-start">
          <div className="order-1 min-w-0 lg:order-none">
            {preview ? <StylePreviewPage preview={preview} stale={previewQuery.isPlaceholderData || previewKey !== styleKey} /> : <p className="text-sm text-muted">{t.preparingPreview}</p>}
            {previewError && <p className="mt-2 text-xs text-danger">{format(t.previewError, { error: previewError })}</p>}
          </div>
          {!template.builtin && (
            <div className="order-3 min-w-0 lg:order-none">
              <TemplateHistory versions={versions} canRestore={template.editable} busy={busy} onRestore={restore} />
            </div>
          )}
        </div>
      </div>

      {template.editable && (dirty || savedNotice) && (
        <div className="sticky bottom-0 z-10 -mx-4 mt-6 flex items-center justify-end gap-3 border-t border-line bg-surface/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6">
          {dirty ? (
            <>
              <span className="mr-auto text-sm text-muted">{t.unsaved}</span>
              <button type="button" onClick={() => setDraft(null)} disabled={busy} className="text-sm font-medium text-muted hover:text-accent">
                {t.discard}
              </button>
              <Button type="button" onClick={() => save()} disabled={!draft.name.trim()} loading={busy} loadingLabel={t.saving}>
                {t.save}
              </Button>
            </>
          ) : (
            <span className="text-sm text-success">{format(t.savedAs, { version: template.version ?? "" })}</span>
          )}
        </div>
      )}
    </Shell>
  );
}

function Shell({ children, backLink }: { children: ReactNode; backLink?: ReactNode }) {
  return (
    <AppShell>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
        {backLink && <div className="mb-4">{backLink}</div>}
        {children}
      </main>
    </AppShell>
  );
}
