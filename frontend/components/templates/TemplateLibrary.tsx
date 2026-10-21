"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Copy, FileUp, Loader2, Pencil, Plus, Star, Trash2 } from "lucide-react";
import { useRef, useState } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { JobProgressBar } from "@/components/JobProgressBar";
import { ReferenceStyleSummary } from "@/components/ReferenceStyleSummary";
import { TemplatePreviewSample } from "@/components/TemplatePreviewSample";
import { categoryLabel } from "@/components/templates/categories";
import { templateText } from "@/components/templates/templateText";
import { buttonClasses } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { fieldClasses } from "@/components/ui/TextField";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages/en";
import { createTemplate, deleteTemplate, duplicateTemplate, extractReferenceStyle, setDefaultTemplate, TemplateConflictError, updateTemplate } from "@/services/api";
import { useInvalidateTemplates, useTemplates } from "@/services/queries";
import type { JobProgress, ReferenceStyle, Template } from "@/types/document";

const actionBase = "flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium text-muted transition-colors hover:bg-surface-muted disabled:opacity-50";
const actionButton = `${actionBase} hover:text-foreground`;
const dangerAction = `${actionBase} hover:text-danger`;

function message(error: unknown, t: Messages["templatesPage"]): string {
  if (error instanceof TemplateConflictError) return t.conflict;
  return error instanceof Error ? error.message : t.somethingWrong;
}

/** The template gallery: built-ins, then the workspace's own, with every
 * management action (open, duplicate, default, rename, delete). */
export function TemplateLibrary() {
  const { m } = useI18n();
  const t = m.templatesPage;
  const router = useRouter();
  const { data: templates, error: loadError } = useTemplates();
  const invalidateTemplates = useInvalidateTemplates();
  const [actionError, setError] = useState<string | null>(null);
  const error = actionError ?? (loadError ? message(loadError, t) : null);
  const [busy, setBusy] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);

  async function act(key: string, action: () => Promise<void>) {
    setBusy(key);
    setError(null);
    try {
      await action();
    } catch (reason) {
      setError(message(reason, t));
    } finally {
      setBusy(null);
      await invalidateTemplates().catch(() => undefined);
    }
  }

  const createBlank = () =>
    act("new", async () => {
      const created = await createTemplate({ name: t.untitled });
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
      setError(message(reason, t));
    } finally {
      if (importInput.current) importInput.current.value = "";
    }
  }

  const saveImport = () =>
    act("import", async () => {
      if (!importing?.reference) return;
      const created = await createTemplate({
        name: importing.name.trim() || importing.reference.suggestedName,
        description: format(t.lookOfDescription, { name: importing.file.name }),
        styleSystem: importing.reference.styleSystem,
      });
      router.push(`/templates/${created.id}`);
    });

  const builtins = templates?.filter((template) => template.builtin) ?? [];
  const own = templates?.filter((template) => !template.builtin) ?? [];

  const card = (template: Template) => (
    <li key={template.id} className={`flex flex-col rounded-2xl border bg-surface p-4 shadow-card ${template.isDefault ? "border-accent ring-1 ring-accent" : "border-line"}`}>
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
            aria-label={t.newName}
            value={renaming.name}
            maxLength={255}
            onChange={(event) => setRenaming({ id: template.id, name: event.target.value })}
            className="h-8 min-w-0 flex-1 rounded-lg border border-accent bg-surface px-2 text-sm text-foreground focus:outline-none"
          />
          <button type="submit" className="text-xs font-medium text-accent">
            {t.save}
          </button>
          <button type="button" onClick={() => setRenaming(null)} className="text-xs font-medium text-muted">
            {t.cancel}
          </button>
        </form>
      ) : (
        <Link href={`/templates/${template.id}`} className="group">
          <span className="flex items-start justify-between gap-2">
            <span className="font-medium text-foreground group-hover:text-accent">{templateText(template, m).name}</span>
            {template.isDefault && <span className="shrink-0 rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-accent">{t.default}</span>}
          </span>
        </Link>
      )}
      <span className="mt-0.5 text-xs text-muted">
        {categoryLabel(template.category, m)}
        {!template.builtin && template.version !== null && format(t.versionShort, { version: template.version })}
      </span>
      {templateText(template, m).description && <p className="mt-2 line-clamp-2 text-sm text-muted">{templateText(template, m).description}</p>}
      <Link href={`/templates/${template.id}`} tabIndex={-1} aria-hidden="true" className="mt-auto block">
        <TemplatePreviewSample styles={template.previewStyles} className="h-32" />
      </Link>

      {confirmingDelete === template.id ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
          <span className="flex-1">{t.deleteAsk}</span>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() =>
              act(template.id, async () => {
                await deleteTemplate(template.id);
                setConfirmingDelete(null);
              })
            }
            className="rounded-full bg-danger px-3 py-1 font-medium text-white hover:brightness-110 disabled:opacity-50"
          >
            {t.delete}
          </button>
          <button type="button" onClick={() => setConfirmingDelete(null)} className="font-medium hover:text-accent">
            {t.cancel}
          </button>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-1">
          <Link href={`/templates/${template.id}`} className={actionButton}>
            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
            {template.editable ? t.edit : t.view}
          </Link>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() =>
              act(template.id, async () => {
                const copy = await duplicateTemplate(template.id);
                router.push(`/templates/${copy.id}`);
              })
            }
            className={actionButton}
          >
            <Copy className="h-3.5 w-3.5" aria-hidden="true" /> {t.duplicate}
          </button>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() =>
              act(template.id, async () => {
                await setDefaultTemplate(template.isDefault ? null : template.id);
              })
            }
            className={actionButton}
            title={template.isDefault ? t.stopDefaultHint : t.makeDefaultHint}
          >
            <Star className={`h-3.5 w-3.5 ${template.isDefault ? "fill-accent text-accent" : ""}`} aria-hidden="true" />
            {template.isDefault ? t.default : t.makeDefault}
          </button>
          {template.editable && (
            <>
              <button type="button" disabled={busy !== null} onClick={() => setRenaming({ id: template.id, name: template.name })} className={actionButton}>
                {t.rename}
              </button>
              <button type="button" disabled={busy !== null} onClick={() => setConfirmingDelete(template.id)} className={dangerAction}>
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> {t.delete}
              </button>
            </>
          )}
          {busy === template.id && <Loader2 className="ml-1 h-3.5 w-3.5 animate-spin text-muted" aria-label={t.working} />}
        </div>
      )}
    </li>
  );

  return (
    <AppShell>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{t.title}</h1>
            <p className="mt-1 max-w-2xl text-sm text-muted">{t.intro}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={importInput}
              type="file"
              accept=".docx"
              className="sr-only"
              aria-label={t.importInput}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void readImport(file);
              }}
            />
            <button
              type="button"
              onClick={() => importInput.current?.click()}
              disabled={busy !== null || (importing !== null && importing.reference === null)}
              className={buttonClasses({ variant: "secondary" })}
            >
              <FileUp className="h-4 w-4" aria-hidden="true" /> {t.importWord}
            </button>
            <button type="button" onClick={createBlank} disabled={busy !== null} className={buttonClasses()}>
              <Plus className="h-4 w-4" aria-hidden="true" /> {t.newTemplate}
            </button>
          </div>
        </div>

        {importing && (
          <section aria-label={t.importRegion} className="mt-6 max-w-xl rounded-2xl border border-line bg-surface p-4 shadow-card">
            {importing.reference === null ? (
              <JobProgressBar progress={importProgress} label={format(t.reading, { name: importing.file.name })} />
            ) : (
              <form
                className="flex flex-col gap-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  saveImport();
                }}
              >
                <p className="text-sm font-medium text-foreground">{format(t.lookOf, { name: importing.file.name })}</p>
                <ReferenceStyleSummary reference={importing.reference} />
                <label className="flex flex-col gap-1 text-xs font-medium text-muted">
                  {t.templateName}
                  <input value={importing.name} maxLength={255} onChange={(event) => setImporting({ ...importing, name: event.target.value })} className={`${fieldClasses} h-10`} />
                </label>
                <div className="flex items-center gap-3">
                  <button type="submit" disabled={busy !== null} className={buttonClasses({ size: "sm" })}>
                    {busy === "import" ? t.saving : t.saveAndOpen}
                  </button>
                  <button type="button" onClick={() => setImporting(null)} className="text-sm text-muted hover:text-accent">
                    {t.cancel}
                  </button>
                </div>
              </form>
            )}
          </section>
        )}

        {error && (
          <div className="mt-4">
            <Notice tone="error">{error}</Notice>
          </div>
        )}

        {templates === undefined ? (
          !loadError && (
            <p className="mt-8 flex items-center gap-2 text-sm text-muted">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {t.loading}
            </p>
          )
        ) : (
          <>
            <h2 className="mt-8 text-sm font-semibold uppercase tracking-wide text-muted">{t.yours}</h2>
            {own.length === 0 ? (
              <p className="mt-3 rounded-2xl border border-dashed border-line-strong px-4 py-6 text-sm text-muted">{t.noneYet}</p>
            ) : (
              <ul className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{own.map(card)}</ul>
            )}

            <h2 className="mt-10 text-sm font-semibold uppercase tracking-wide text-muted">{t.builtIn}</h2>
            <ul className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{builtins.map(card)}</ul>
          </>
        )}
      </main>
    </AppShell>
  );
}
