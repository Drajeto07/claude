"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Copy, FileUp, Loader2, Pencil, Plus, Star, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { JobProgressBar } from "@/components/JobProgressBar";
import { ReferenceStyleSummary } from "@/components/ReferenceStyleSummary";
import { TemplatePreviewSample } from "@/components/TemplatePreviewSample";
import { categoryLabel } from "@/components/templates/categories";
import {
  createTemplate,
  deleteTemplate,
  duplicateTemplate,
  extractReferenceStyle,
  listTemplates,
  setDefaultTemplate,
  TemplateConflictError,
  updateTemplate,
} from "@/services/api";
import type { JobProgress, ReferenceStyle, Template } from "@/types/document";

const actionBase =
  "flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium text-zinc-600 transition-colors hover:bg-zinc-100 disabled:opacity-50 dark:text-zinc-400 dark:hover:bg-zinc-800";
const actionButton = `${actionBase} hover:text-zinc-900 dark:hover:text-zinc-50`;
const dangerAction = `${actionBase} hover:text-red-600 dark:hover:text-red-400`;

function message(error: unknown): string {
  if (error instanceof TemplateConflictError) return "That template was changed somewhere else. The list has been refreshed; try again.";
  return error instanceof Error ? error.message : "Something went wrong.";
}

/** The template gallery: built-ins, then the workspace's own, with every
 * management action (open, duplicate, default, rename, delete). */
export function TemplateLibrary() {
  const router = useRouter();
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);

  const refresh = useCallback(async () => setTemplates(await listTemplates()), []);

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch((reason) => setError(message(reason)));
  }, []);

  async function act(key: string, action: () => Promise<void>) {
    setBusy(key);
    setError(null);
    try {
      await action();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(null);
      await refresh().catch(() => undefined);
    }
  }

  const createBlank = () =>
    act("new", async () => {
      const created = await createTemplate({ name: "Untitled template" });
      router.push(`/templates/${created.id}`);
    });

  // Import from Word (Format by Example): read the file's look, review it, save it.
  const importInput = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState<{ file: File; reference: ReferenceStyle | null; name: string } | null>(null);
  const [importProgress, setImportProgress] = useState<JobProgress>({ stage: "queued", progress: 0 });

  async function readImport(file: File) {
    setImporting({ file, reference: null, name: "" });
    setImportProgress({ stage: "queued", progress: 0 });
    setError(null);
    try {
      const reference = await extractReferenceStyle(file, setImportProgress);
      setImporting({ file, reference, name: reference.suggestedName });
    } catch (reason) {
      setImporting(null);
      setError(message(reason));
    } finally {
      if (importInput.current) importInput.current.value = "";
    }
  }

  const saveImport = () =>
    act("import", async () => {
      if (!importing?.reference) return;
      const created = await createTemplate({
        name: importing.name.trim() || importing.reference.suggestedName,
        description: `The look of ${importing.file.name}.`,
        styleSystem: importing.reference.styleSystem,
      });
      router.push(`/templates/${created.id}`);
    });

  const builtins = templates?.filter((template) => template.builtin) ?? [];
  const own = templates?.filter((template) => !template.builtin) ?? [];

  const card = (template: Template) => (
    <li
      key={template.id}
      className={`flex flex-col rounded-xl border bg-white p-4 shadow-sm dark:bg-zinc-900 ${
        template.isDefault ? "border-accent" : "border-zinc-200 dark:border-zinc-800"
      }`}
    >
      {renaming?.id === template.id ? (
        <form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            const name = renaming.name.trim();
            if (!name) return;
            act(template.id, async () => {
              await updateTemplate(template.id, template.version, { name });
              setRenaming(null);
            });
          }}
        >
          <input
            autoFocus
            aria-label="New name"
            value={renaming.name}
            maxLength={255}
            onChange={(event) => setRenaming({ id: template.id, name: event.target.value })}
            className="min-w-0 flex-1 rounded-md border border-accent bg-white px-2 py-1 text-sm text-zinc-900 focus:outline-none dark:bg-zinc-950 dark:text-zinc-50"
          />
          <button type="submit" className="text-xs font-medium text-accent">
            Save
          </button>
          <button type="button" onClick={() => setRenaming(null)} className="text-xs font-medium text-zinc-500">
            Cancel
          </button>
        </form>
      ) : (
        <Link href={`/templates/${template.id}`} className="group">
          <span className="flex items-start justify-between gap-2">
            <span className="font-medium text-zinc-900 group-hover:text-accent dark:text-zinc-50">{template.name}</span>
            {template.isDefault && (
              <span className="shrink-0 rounded-full bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent">Default</span>
            )}
          </span>
        </Link>
      )}
      <span className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
        {categoryLabel(template.category)}
        {!template.builtin && template.version !== null && ` · version ${template.version}`}
      </span>
      {template.description && <p className="mt-2 line-clamp-2 text-sm text-zinc-600 dark:text-zinc-400">{template.description}</p>}
      <Link href={`/templates/${template.id}`} tabIndex={-1} aria-hidden="true" className="mt-auto block">
        <TemplatePreviewSample styles={template.previewStyles} className="h-32" />
      </Link>

      {confirmingDelete === template.id ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
          <span className="flex-1">Delete? Documents formatted with it keep their formatting.</span>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => act(template.id, async () => { await deleteTemplate(template.id); setConfirmingDelete(null); })}
            className="rounded-full bg-red-600 px-3 py-1 font-medium text-white hover:bg-red-700 disabled:opacity-50"
          >
            Delete
          </button>
          <button type="button" onClick={() => setConfirmingDelete(null)} className="font-medium hover:text-accent">
            Cancel
          </button>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-1">
          <Link href={`/templates/${template.id}`} className={actionButton}>
            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
            {template.editable ? "Edit" : "View"}
          </Link>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => act(template.id, async () => { const copy = await duplicateTemplate(template.id); router.push(`/templates/${copy.id}`); })}
            className={actionButton}
          >
            <Copy className="h-3.5 w-3.5" aria-hidden="true" /> Duplicate
          </button>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => act(template.id, async () => { await setDefaultTemplate(template.isDefault ? null : template.id); })}
            className={actionButton}
            title={template.isDefault ? "Stop preselecting it for new documents" : "Preselect it for new documents"}
          >
            <Star className={`h-3.5 w-3.5 ${template.isDefault ? "fill-accent text-accent" : ""}`} aria-hidden="true" />
            {template.isDefault ? "Default" : "Make default"}
          </button>
          {template.editable && (
            <>
              <button type="button" disabled={busy !== null} onClick={() => setRenaming({ id: template.id, name: template.name })} className={actionButton}>
                Rename
              </button>
              <button type="button" disabled={busy !== null} onClick={() => setConfirmingDelete(template.id)} className={dangerAction}>
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Delete
              </button>
            </>
          )}
          {busy === template.id && <Loader2 className="ml-1 h-3.5 w-3.5 animate-spin text-zinc-400" aria-label="Working" />}
        </div>
      )}
    </li>
  );

  return (
    <div className="flex flex-1 flex-col bg-zinc-50 dark:bg-black">
      <AppHeader />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Templates</h1>
            <p className="mt-1 max-w-2xl text-sm text-zinc-600 dark:text-zinc-400">
              A template is a complete look for a document: page, fonts, headings, lists, tables, captions, header and footer.
              The default one is preselected when you create a document.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={importInput}
              type="file"
              accept=".docx"
              className="sr-only"
              aria-label="Word document to import the look of"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void readImport(file);
              }}
            />
            <button
              type="button"
              onClick={() => importInput.current?.click()}
              disabled={busy !== null || (importing !== null && importing.reference === null)}
              className="flex items-center gap-1.5 rounded-full border border-zinc-300 bg-white px-4 py-2 text-sm font-medium text-zinc-700 transition-colors hover:border-accent hover:text-accent disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
            >
              <FileUp className="h-4 w-4" aria-hidden="true" /> Import from Word
            </button>
            <button
              type="button"
              onClick={createBlank}
              disabled={busy !== null}
              className="flex items-center gap-1.5 rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              <Plus className="h-4 w-4" aria-hidden="true" /> New template
            </button>
          </div>
        </div>

        {importing && (
          <section aria-label="Import from Word" className="mt-6 max-w-xl rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            {importing.reference === null ? (
              <JobProgressBar progress={importProgress} label={`Reading the look of ${importing.file.name}`} />
            ) : (
              <form
                className="flex flex-col gap-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  saveImport();
                }}
              >
                <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">The look of {importing.file.name}</p>
                <ReferenceStyleSummary reference={importing.reference} />
                <label className="flex flex-col gap-1 text-xs font-medium text-zinc-600 dark:text-zinc-400">
                  Template name
                  <input
                    value={importing.name}
                    maxLength={255}
                    onChange={(event) => setImporting({ ...importing, name: event.target.value })}
                    className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 focus:border-accent focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                  />
                </label>
                <div className="flex items-center gap-3">
                  <button
                    type="submit"
                    disabled={busy !== null}
                    className="rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50"
                  >
                    {busy === "import" ? "Saving…" : "Save and open"}
                  </button>
                  <button type="button" onClick={() => setImporting(null)} className="text-sm text-zinc-500 hover:text-accent">
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </section>
        )}

        {error && (
          <p role="alert" className="mt-4 text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}

        {templates === null ? (
          <p className="mt-8 flex items-center gap-2 text-sm text-zinc-500">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading templates…
          </p>
        ) : (
          <>
            <h2 className="mt-8 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Your templates</h2>
            {own.length === 0 ? (
              <p className="mt-3 rounded-xl border border-dashed border-zinc-300 px-4 py-6 text-sm text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
                None yet. Duplicate a built-in template below to adjust it, start a new one, import the look of a Word
                document, or save a document&rsquo;s formatting as a template from the Templates panel in the editor.
              </p>
            ) : (
              <ul className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{own.map(card)}</ul>
            )}

            <h2 className="mt-10 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Built-in</h2>
            <ul className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{builtins.map(card)}</ul>
          </>
        )}
      </main>
    </div>
  );
}
