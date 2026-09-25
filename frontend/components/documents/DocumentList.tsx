"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ClipboardPaste, FileDiff, Loader2, Search, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { formatDateTime, formatWhen, sourceLabel } from "@/lib/format";
import { useDebouncedValue } from "@/lib/useDebouncedValue";
import { deleteDocument, errorMessage, type DocumentListParams } from "@/services/api";
import { queryKeys, useDocumentList } from "@/services/queries";
import type { DocumentSummary } from "@/types/document";

const PAGE_SIZE = 20;
const SORTS: { value: NonNullable<DocumentListParams["sort"]>; label: string }[] = [
  { value: "updated", label: "Last changed" },
  { value: "created", label: "Newest" },
  { value: "title", label: "Title" },
];

export function StatusBadge({ document }: { document: DocumentSummary }) {
  if (document.status === "draft") {
    return <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">Draft</span>;
  }
  return (
    <span className="rounded-full bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent" title={document.formattedAt ? `Formatted ${formatDateTime(document.formattedAt)}` : undefined}>
      Formatted{document.templateName ? ` · ${document.templateName}` : ""}
    </span>
  );
}

/**
 * All of the user's documents (корекции.docx §64): title, when it last changed,
 * where it came from, whether it is formatted, and what can be done with it.
 * Deleting asks first and is for good (§32).
 */
export function DocumentList() {
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

  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const lastPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);

  async function confirmDelete() {
    if (!deleting) return;
    setBusy(true);
    setDeleteError(null);
    try {
      await deleteDocument(deleting.id);
      setDeleting(null);
      if (items.length === 1 && page > 0) setPage(page - 1);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.allDocumentLists }),
        queryClient.invalidateQueries({ queryKey: queryKeys.usage }),
      ]);
    } catch (err) {
      setDeleteError(errorMessage(err, "The document couldn't be deleted."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col bg-zinc-50 dark:bg-black">
      <AppHeader />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Documents</h1>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">{isPending ? "Loading…" : `${total} document${total === 1 ? "" : "s"}`}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link href="/new?mode=upload" className="flex items-center gap-1.5 rounded-full border border-zinc-300 bg-white px-4 py-2 text-sm font-medium text-zinc-700 hover:border-accent hover:text-accent dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
              <Upload className="h-4 w-4" aria-hidden="true" /> Upload
            </Link>
            <Link href="/new" className="flex items-center gap-1.5 rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-foreground hover:opacity-90">
              <ClipboardPaste className="h-4 w-4" aria-hidden="true" /> New document
            </Link>
          </div>
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <label className="relative min-w-[14rem] flex-1 sm:max-w-sm">
            <span className="sr-only">Search by title</span>
            <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-zinc-400" aria-hidden="true" />
            <input
              type="search"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(0);
              }}
              placeholder="Search by title"
              className="w-full rounded-full border border-zinc-300 bg-white py-2 pr-3 pl-9 text-sm text-zinc-900 focus:border-accent focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
            Sort by
            <select
              value={sort}
              onChange={(event) => {
                setSort(event.target.value as typeof sort);
                setPage(0);
              }}
              className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
            >
              {SORTS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          {isPlaceholderData && <Loader2 className="h-4 w-4 animate-spin text-zinc-400" aria-label="Loading" />}
        </div>

        {error && (
          <p role="alert" className="mt-4 text-sm text-red-600 dark:text-red-400">
            {errorMessage(error)}
          </p>
        )}

        {!isPending && items.length === 0 && !error && (
          <div className="mt-6 rounded-xl border border-dashed border-zinc-300 px-6 py-10 text-center text-sm text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
            {q ? <>No document titles match &ldquo;{q}&rdquo;.</> : <>No documents yet. Paste some text or upload a file to start.</>}
          </div>
        )}

        {items.length > 0 && (
          <div className="mt-6 overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-zinc-200 bg-zinc-50 text-xs tracking-wide text-zinc-500 uppercase dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-400">
                <tr>
                  <th scope="col" className="px-4 py-2.5 font-medium">Title</th>
                  <th scope="col" className="hidden px-4 py-2.5 font-medium sm:table-cell">Changed</th>
                  <th scope="col" className="hidden px-4 py-2.5 font-medium md:table-cell">Source</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Status</th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {items.map((document) => (
                  <tr key={document.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-950">
                    <td className="max-w-[16rem] px-4 py-3">
                      <Link href={`/documents/${document.id}`} className="block truncate font-medium text-zinc-900 hover:text-accent dark:text-zinc-50">
                        {document.title}
                      </Link>
                    </td>
                    <td className="hidden px-4 py-3 whitespace-nowrap text-zinc-500 sm:table-cell dark:text-zinc-400" title={formatDateTime(document.updatedAt)}>
                      {formatWhen(document.updatedAt)}
                    </td>
                    <td className="hidden px-4 py-3 text-zinc-500 md:table-cell dark:text-zinc-400" title={document.originalFilename ?? undefined}>
                      {sourceLabel(document.sourceType)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge document={document} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        <Link
                          href={`/documents/${document.id}/compare`}
                          title="Before and after"
                          aria-label={`Before and after: ${document.title}`}
                          className="flex h-8 w-8 items-center justify-center rounded-full text-zinc-500 hover:bg-zinc-100 hover:text-accent dark:hover:bg-zinc-800"
                        >
                          <FileDiff className="h-4 w-4" aria-hidden="true" />
                        </Link>
                        <button
                          type="button"
                          onClick={() => {
                            setDeleteError(null);
                            setDeleting(document);
                          }}
                          title="Delete"
                          aria-label={`Delete ${document.title}`}
                          className="flex h-8 w-8 items-center justify-center rounded-full text-zinc-500 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40"
                        >
                          <Trash2 className="h-4 w-4" aria-hidden="true" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {total > PAGE_SIZE && (
          <nav aria-label="Pages" className="mt-4 flex items-center justify-between text-sm text-zinc-600 dark:text-zinc-400">
            <span>
              {page * PAGE_SIZE + 1}–{Math.min(total, (page + 1) * PAGE_SIZE)} of {total}
            </span>
            <span className="flex gap-2">
              <button type="button" onClick={() => setPage(page - 1)} disabled={page === 0} className="rounded-full border border-zinc-300 px-3 py-1.5 hover:border-accent disabled:opacity-40 dark:border-zinc-700">
                Previous
              </button>
              <button type="button" onClick={() => setPage(page + 1)} disabled={page >= lastPage} className="rounded-full border border-zinc-300 px-3 py-1.5 hover:border-accent disabled:opacity-40 dark:border-zinc-700">
                Next
              </button>
            </span>
          </nav>
        )}
      </main>

      {deleting && (
        <ConfirmDialog
          title="Delete this document for good?"
          confirmLabel="Delete for good"
          busy={busy}
          error={deleteError}
          onConfirm={() => void confirmDelete()}
          onCancel={() => setDeleting(null)}
        >
          <p>
            &ldquo;{deleting.title}&rdquo; goes, with its version history and the files of its exports. This can&rsquo;t be undone.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
