"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Copy, Loader2, Star, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { AppHeader } from "@/components/AppHeader";
import { StylePreviewPage } from "@/components/templates/StylePreviewPage";
import { StyleSystemForm } from "@/components/templates/StyleSystemForm";
import { TemplateHistory } from "@/components/templates/TemplateHistory";
import { TEMPLATE_CATEGORIES, categoryLabel } from "@/components/templates/categories";
import {
  deleteTemplate,
  duplicateTemplate,
  getTemplate,
  listTemplateVersions,
  previewStyleSystem,
  restoreTemplateVersion,
  setDefaultTemplate,
  TemplateConflictError,
  updateTemplate,
} from "@/services/api";
import type { StylePreview, StyleSystem, Template, TemplateVersion } from "@/types/document";

type Draft = { name: string; category: string; description: string; styleSystem: StyleSystem };

function toDraft(template: Template): Draft {
  return { name: template.name, category: template.category, description: template.description, styleSystem: template.styleSystem };
}

const PREVIEW_DEBOUNCE_MS = 300;

const inputClass =
  "w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 focus:border-accent focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50 disabled:cursor-not-allowed disabled:bg-zinc-50 disabled:text-zinc-500 dark:disabled:bg-zinc-900 dark:disabled:text-zinc-400";
const pillBase =
  "flex items-center gap-1.5 rounded-full border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300";
const pillButton = `${pillBase} hover:border-accent hover:text-accent`;
const dangerPillButton = `${pillBase} hover:border-red-500 hover:text-red-600`;

function message(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}

/**
 * View and edit one template: name and description, every part of its style
 * system, a live page preview resolved by the backend engine, its saved
 * versions, and default/duplicate/delete. Built-ins open read-only.
 */
export function TemplateEditor({ templateId }: { templateId: string }) {
  const router = useRouter();
  const [template, setTemplate] = useState<Template | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [versions, setVersions] = useState<TemplateVersion[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedNotice, setSavedNotice] = useState(false);
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [preview, setPreview] = useState<{ key: string; result: StylePreview } | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const fetchTemplate = useCallback(async () => {
    const loaded = await getTemplate(templateId);
    return { loaded, history: loaded.builtin ? [] : await listTemplateVersions(templateId) };
  }, [templateId]);

  function show({ loaded, history }: { loaded: Template; history: TemplateVersion[] }) {
    setTemplate(loaded);
    setDraft(toDraft(loaded));
    setVersions(history);
    setConflict(false);
  }

  useEffect(() => {
    let cancelled = false;
    fetchTemplate()
      .then((result) => {
        if (!cancelled) show(result);
      })
      .catch((reason) => {
        if (!cancelled) setLoadError(message(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [fetchTemplate]);

  // Live preview: the unsaved style system, resolved by the real engine.
  const styleKey = draft ? JSON.stringify(draft.styleSystem) : null;
  useEffect(() => {
    if (!draft || styleKey === null) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      previewStyleSystem(draft.styleSystem, controller.signal)
        .then((result) => {
          setPreview({ key: styleKey, result });
          setPreviewError(null);
        })
        .catch((reason) => {
          if (!controller.signal.aborted) setPreviewError(message(reason));
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // styleKey captures every change to draft.styleSystem.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [styleKey]);

  const dirty = Boolean(template && draft && JSON.stringify(toDraft(template)) !== JSON.stringify(draft));

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
      setTemplate(saved);
      setDraft(toDraft(saved));
      setConflict(false);
      setVersions(await listTemplateVersions(saved.id));
      setSavedNotice(true);
    });

  const restore = (number: number) =>
    run(async () => {
      if (!template) return;
      if (dirty && !window.confirm("Restoring this version replaces your unsaved changes. Continue?")) return;
      const restored = await restoreTemplateVersion(template.id, number, template.version);
      setTemplate(restored);
      setDraft(toDraft(restored));
      setVersions(await listTemplateVersions(restored.id));
      setSavedNotice(true);
    });

  const toggleDefault = () =>
    run(async () => {
      if (!template) return;
      const defaultId = await setDefaultTemplate(template.isDefault ? null : template.id);
      setTemplate({ ...template, isDefault: defaultId === template.id });
    });

  const duplicate = () =>
    run(async () => {
      if (!template) return;
      const copy = await duplicateTemplate(template.id);
      router.push(`/templates/${copy.id}`);
    });

  const remove = () =>
    run(async () => {
      if (!template) return;
      await deleteTemplate(template.id);
      router.push("/templates");
    });

  if (loadError) {
    return (
      <Shell>
        <p className="text-sm text-red-600 dark:text-red-400">{loadError}</p>
      </Shell>
    );
  }
  if (!template || !draft) {
    return (
      <Shell>
        <p className="flex items-center gap-2 text-sm text-zinc-500">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading template…
        </p>
      </Shell>
    );
  }

  const categories = TEMPLATE_CATEGORIES.some((category) => category.value === draft.category)
    ? TEMPLATE_CATEGORIES
    : [...TEMPLATE_CATEGORIES, { value: draft.category, label: categoryLabel(draft.category) }];

  return (
    <Shell
      backLink={
        <Link
          href="/templates"
          onClick={(event) => {
            if (dirty && !window.confirm("Leave without saving your changes?")) event.preventDefault();
          }}
          className="inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-accent dark:text-zinc-400"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" /> All templates
        </Link>
      }
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">{template.name}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
            <span>{template.builtin ? "Built-in template" : `Version ${template.version}`}</span>
            <span>· {categoryLabel(template.category)}</span>
            {template.isDefault && <span className="rounded-full bg-accent/10 px-2 py-0.5 font-medium text-accent">Workspace default</span>}
            {template.sourceDocumentId && (
              <Link href={`/documents/${template.sourceDocumentId}`} className="text-accent hover:underline">
                · saved from a document
              </Link>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={toggleDefault} disabled={busy} className={pillButton}>
            <Star className={`h-3.5 w-3.5 ${template.isDefault ? "fill-accent text-accent" : ""}`} aria-hidden="true" />
            {template.isDefault ? "Default for new documents" : "Use for new documents"}
          </button>
          <button type="button" onClick={duplicate} disabled={busy} className={pillButton}>
            <Copy className="h-3.5 w-3.5" aria-hidden="true" /> Duplicate
          </button>
          {template.editable &&
            (confirmingDelete ? (
              <span className="flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
                Delete for good? Documents keep their formatting.
                <button type="button" onClick={remove} disabled={busy} className="rounded-full bg-red-600 px-3 py-1.5 font-medium text-white hover:bg-red-700">
                  Delete
                </button>
                <button type="button" onClick={() => setConfirmingDelete(false)} className="font-medium hover:text-accent">
                  Cancel
                </button>
              </span>
            ) : (
              <button type="button" onClick={() => setConfirmingDelete(true)} disabled={busy} className={dangerPillButton}>
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Delete
              </button>
            ))}
        </div>
      </div>

      {!template.editable && (
        <p className="mt-4 rounded-lg border border-zinc-200 bg-zinc-50 px-4 py-3 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
          {template.builtin ? "Built-in templates can't be changed." : "Only the person who made this template or the workspace owner can change it."}{" "}
          Duplicate it to make a version of your own.
        </p>
      )}

      {conflict && (
        <div role="alert" className="mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200">
          <span className="flex-1">This template was saved somewhere else since you opened it, so your changes weren&rsquo;t saved.</span>
          <button type="button" onClick={() => run(async () => show(await fetchTemplate()))} className="font-medium underline">
            Load the latest version
          </button>
          <button type="button" onClick={() => save(true)} className="font-medium underline">
            Save mine over it
          </button>
        </div>
      )}
      {error && (
        <p role="alert" className="mt-4 text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
        <fieldset disabled={!template.editable || busy} className="order-2 flex min-w-0 flex-col gap-3 lg:order-none">
          <legend className="sr-only">Template settings</legend>
          <section className="grid gap-3 rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
              Name
              <input className={inputClass} value={draft.name} maxLength={255} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
              Category
              <select className={inputClass} value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.target.value })}>
                {categories.map((category) => (
                  <option key={category.value} value={category.value}>
                    {category.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-zinc-600 dark:text-zinc-400 sm:col-span-2">
              Description
              <textarea
                className={`${inputClass} min-h-[4.5rem]`}
                value={draft.description}
                maxLength={2000}
                onChange={(event) => setDraft({ ...draft, description: event.target.value })}
              />
            </label>
          </section>
          <StyleSystemForm value={draft.styleSystem} onChange={(styleSystem) => setDraft({ ...draft, styleSystem })} />
        </fieldset>

        {/* One sticky column on wide screens; on narrow ones "contents" lets the
            preview go above the form and the history below it. */}
        <div className="contents lg:sticky lg:top-6 lg:flex lg:min-w-0 lg:flex-col lg:gap-4 lg:self-start">
          <div className="order-1 min-w-0 lg:order-none">
            {preview ? (
              <StylePreviewPage preview={preview.result} stale={preview.key !== styleKey} />
            ) : (
              <p className="text-sm text-zinc-500">Preparing preview…</p>
            )}
            {previewError && <p className="mt-2 text-xs text-red-600 dark:text-red-400">Preview: {previewError}</p>}
          </div>
          {!template.builtin && (
            <div className="order-3 min-w-0 lg:order-none">
              <TemplateHistory versions={versions} canRestore={template.editable} busy={busy} onRestore={restore} />
            </div>
          )}
        </div>
      </div>

      {template.editable && (dirty || savedNotice) && (
        <div className="sticky bottom-0 z-10 -mx-4 mt-6 flex items-center justify-end gap-3 border-t border-zinc-200 bg-white/95 px-4 py-3 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/95 sm:-mx-6 sm:px-6">
          {dirty ? (
            <>
              <span className="mr-auto text-sm text-zinc-500 dark:text-zinc-400">Unsaved changes</span>
              <button type="button" onClick={() => setDraft(toDraft(template))} disabled={busy} className="text-sm font-medium text-zinc-600 hover:text-accent dark:text-zinc-400">
                Discard
              </button>
              <button
                type="button"
                onClick={() => save()}
                disabled={busy || !draft.name.trim()}
                className="rounded-full bg-accent px-5 py-2 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {busy ? "Saving…" : "Save template"}
              </button>
            </>
          ) : (
            <span className="text-sm text-green-700 dark:text-green-400">Saved as version {template.version}.</span>
          )}
        </div>
      )}
    </Shell>
  );
}

function Shell({ children, backLink }: { children: ReactNode; backLink?: ReactNode }) {
  return (
    <div className="flex flex-1 flex-col bg-zinc-50 dark:bg-black">
      <AppHeader />
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
        {backLink && <div className="mb-4">{backLink}</div>}
        {children}
      </main>
    </div>
  );
}
