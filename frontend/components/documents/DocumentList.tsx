"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ClipboardPaste, FileDiff, Loader2, Search, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { SOURCE_LOOK, sourceKey } from "@/components/dashboard/ProjectCard";
import { BatchBar } from "@/components/documents/BatchBar";
import { buttonClasses } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { fieldClasses } from "@/components/ui/TextField";
import { formatDateTime, formatRelative } from "@/i18n/format";
import { useI18n } from "@/i18n/I18nProvider";
import { format, plural } from "@/i18n/locales";
import { useDebouncedValue } from "@/lib/useDebouncedValue";
import { deleteDocument, errorMessage, type DocumentListParams } from "@/services/api";
import { queryKeys, useDocumentList } from "@/services/queries";
import type { DocumentSummary } from "@/types/document";

const PAGE_SIZE = 20;
const SORTS: NonNullable<DocumentListParams["sort"]>[] = ["updated", "created", "title"];
const checkbox = "h-4 w-4 rounded accent-[var(--accent)]";
const rowAction = "flex h-8 w-8 items-center justify-center rounded-full text-muted transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";
const pageButton = "rounded-full border border-line-strong px-3 py-1.5 text-foreground hover:border-accent disabled:opacity-40";

export function StatusBadge({ document }: { document: DocumentSummary }) {
  const { m, locale } = useI18n();
  if (document.status === "draft") {
    return <span className="rounded-full bg-surface-muted px-2 py-0.5 text-xs font-medium text-muted">{m.dashboard.draft}</span>;
  }
  return (
    <span
      className="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent"
      title={document.formattedAt ? format(m.documents.formattedAt, { when: formatDateTime(document.formattedAt, locale) }) : undefined}
    >
      {m.dashboard.formatted}
      {document.templateName ? ` · ${document.templateName}` : ""}
    </span>
  );
}

/**
 * One project in the gallery (S2-025): the card opens it; its tick, "before and after" and delete sit above
 * that. The picture is its kind -- where it came from -- never its content: real first pages are drawn by
 * the server with PDFium (B-028), so the gallery asks for none until that is safe.
 */
function DocumentCard({
  document,
  selected,
  onToggle,
  onDelete,
}: {
  document: DocumentSummary;
  selected: boolean;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const { m, locale } = useI18n();
  const t = m.documents;
  const source = sourceKey(document.sourceType);
  const look = SOURCE_LOOK[source];
  const Icon = look.icon;
  return (
    <li className="group relative flex flex-col overflow-hidden rounded-2xl border border-line bg-surface transition-[box-shadow,border-color] hover:border-line-strong hover:shadow-card has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-accent">
      <div aria-hidden="true" data-testid="project-kind" className="flex h-20 items-center justify-center border-b border-line bg-surface-muted">
        <span className={`flex h-11 w-11 items-center justify-center rounded-2xl ${look.tile}`}>
          <Icon className="h-5 w-5" />
        </span>
      </div>
      <input
        type="checkbox"
        aria-label={format(t.selectOne, { title: document.title })}
        checked={selected}
        onChange={onToggle}
        className={`${checkbox} absolute top-3 left-3 z-10`}
      />
      <div className="flex flex-1 flex-col gap-1 p-4">
        <Link
          href={`/documents/${document.id}`}
          className="truncate text-sm font-semibold text-foreground after:absolute after:inset-0 focus-visible:outline-none group-hover:text-accent"
        >
          {document.title}
        </Link>
        <span className="flex items-center gap-1.5 truncate text-xs text-muted" title={document.originalFilename ?? undefined}>
          <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {m.dashboard.source[source]}
        </span>
        <span className="text-xs text-muted" title={formatDateTime(document.updatedAt, locale)}>
          {format(m.dashboard.edited, { when: formatRelative(document.updatedAt, locale) })}
        </span>
        <div className="mt-auto flex items-center justify-between gap-2 pt-2">
          <span className="min-w-0 truncate">
            <StatusBadge document={document} />
          </span>
          <div className="relative z-10 flex shrink-0 gap-1">
            <Link href={`/documents/${document.id}/compare`} title={t.compare} aria-label={format(t.compareNamed, { title: document.title })} className={`${rowAction} hover:bg-surface-muted hover:text-accent`}>
              <FileDiff className="h-4 w-4" aria-hidden="true" />
            </Link>
            <button type="button" onClick={onDelete} title={t.delete} aria-label={format(t.deleteNamed, { title: document.title })} className={`${rowAction} hover:bg-danger/10 hover:text-danger`}>
              <Trash2 className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
    </li>
  );
}

/**
 * All of the user's documents (корекции.docx §64), as a gallery of cards (S2-025): title, when it last
 * changed, where it came from, whether it is formatted, and what can be done with it. Deleting asks first
 * and is for good (§32).
 */
export function DocumentList() {
  const { m } = useI18n();
  const t = m.documents;
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search.trim(), 300);
  const [sort, setSort] = useState<NonNullable<DocumentListParams["sort"]>>("updated");
  const [page, setPage] = useState(0);
  const params = { q: q || undefined, sort, limit: PAGE_SIZE, offset: page * PAGE_SIZE };
  const { data, isPending, isPlaceholderData, error } = useDocumentList(params);
  const [deleting, setDeleting] = useState<DocumentSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // The documents ticked for a batch (FEAT-001), kept across pages and searches.
  const [selected, setSelected] = useState<string[]>([]);
  const toggle = (id: string) => setSelected((current) => (current.includes(id) ? current.filter((each) => each !== id) : [...current, id]));

  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const lastPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);

  async function confirmDelete() {
    if (!deleting) return;
    setBusy(true);
    setDeleteError(null);
    try {
      await deleteDocument(deleting.id);
      setSelected((current) => current.filter((id) => id !== deleting.id));
      setDeleting(null);
      if (items.length === 1 && page > 0) setPage(page - 1);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.allDocumentLists }),
        queryClient.invalidateQueries({ queryKey: queryKeys.usage }),
      ]);
    } catch (err) {
      setDeleteError(errorMessage(err, t.deleteFailed));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{t.title}</h1>
            <p className="mt-1 text-sm text-muted">{isPending ? m.common.loading : plural(total, t.count)}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link href="/new?mode=upload" className={buttonClasses({ variant: "secondary" })}>
              <Upload className="h-4 w-4" aria-hidden="true" /> {t.upload}
            </Link>
            <Link href="/new" className={buttonClasses()}>
              <ClipboardPaste className="h-4 w-4" aria-hidden="true" /> {t.newDocument}
            </Link>
          </div>
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <label className="relative min-w-[14rem] flex-1 sm:max-w-sm">
            <span className="sr-only">{t.searchLabel}</span>
            <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden="true" />
            <input
              type="search"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(0);
              }}
              placeholder={t.searchPlaceholder}
              className={`${fieldClasses} h-10 pl-9`}
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-muted">
            {t.sortBy}
            <select
              value={sort}
              onChange={(event) => {
                setSort(event.target.value as typeof sort);
                setPage(0);
              }}
              className="h-10 rounded-xl border border-line bg-surface px-2 text-sm text-foreground focus:border-accent focus:outline-none"
            >
              {SORTS.map((option) => (
                <option key={option} value={option}>
                  {t.sorts[option]}
                </option>
              ))}
            </select>
          </label>
          {isPlaceholderData && <Loader2 className="h-4 w-4 animate-spin text-muted" aria-label={t.loading} />}
        </div>

        {error && (
          <div className="mt-4">
            <Notice tone="error">{errorMessage(error)}</Notice>
          </div>
        )}

        {!isPending && items.length === 0 && !error && (
          <div className="mt-6 rounded-2xl border border-dashed border-line-strong px-6 py-10 text-center text-sm text-muted">{q ? format(t.noMatch, { query: q }) : t.empty}</div>
        )}

        {selected.length > 0 && <BatchBar selected={selected} onClear={() => setSelected([])} />}

        {items.length > 0 && (
          <>
            <label className="mt-6 flex w-fit items-center gap-2 text-sm text-muted">
              <input
                type="checkbox"
                checked={items.every((document) => selected.includes(document.id))}
                onChange={(event) =>
                  setSelected((current) =>
                    event.target.checked
                      ? [...current, ...items.map((document) => document.id).filter((id) => !current.includes(id))]
                      : current.filter((id) => !items.some((document) => document.id === id)),
                  )
                }
                className={checkbox}
              />
              {t.selectPage}
            </label>
            <ul className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {items.map((document) => (
                <DocumentCard
                  key={document.id}
                  document={document}
                  selected={selected.includes(document.id)}
                  onToggle={() => toggle(document.id)}
                  onDelete={() => {
                    setDeleteError(null);
                    setDeleting(document);
                  }}
                />
              ))}
            </ul>
          </>
        )}

        {total > PAGE_SIZE && (
          <nav aria-label={t.pages} className="mt-4 flex items-center justify-between text-sm text-muted">
            <span>{format(t.range, { from: page * PAGE_SIZE + 1, to: Math.min(total, (page + 1) * PAGE_SIZE), total })}</span>
            <span className="flex gap-2">
              <button type="button" onClick={() => setPage(page - 1)} disabled={page === 0} className={pageButton}>
                {t.previous}
              </button>
              <button type="button" onClick={() => setPage(page + 1)} disabled={page >= lastPage} className={pageButton}>
                {t.next}
              </button>
            </span>
          </nav>
        )}
      </main>

      {deleting && (
        <ConfirmDialog title={t.deleteTitle} confirmLabel={t.deleteConfirm} busy={busy} error={deleteError} onConfirm={() => void confirmDelete()} onCancel={() => setDeleting(null)}>
          <p>{format(t.deleteText, { title: deleting.title })}</p>
        </ConfirmDialog>
      )}
    </AppShell>
  );
}
