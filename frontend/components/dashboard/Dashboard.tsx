"use client";

import { ArrowRight, ClipboardPaste, Download, FileSearch, LayoutTemplate, Loader2, Upload } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { AppHeader } from "@/components/AppHeader";
import { StatusBadge } from "@/components/documents/DocumentList";
import { formatBytes, formatDateTime, formatWhen } from "@/lib/format";
import { errorMessage, jobFileUrl } from "@/services/api";
import { useBilling, useCurrentUser, useDocumentList, useRecentExports, useTemplates, useUsage } from "@/services/queries";
import type { ExportJobResult } from "@/types/document";

const monthFormat = new Intl.DateTimeFormat(undefined, { month: "long" });

function Card({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Loading() {
  return (
    <p className="flex items-center gap-2 text-sm text-zinc-500">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading…
    </p>
  );
}

function QuickAction({ href, icon, title, description }: { href: string; icon: ReactNode; title: string; description: string }) {
  return (
    <Link
      href={href}
      className="group flex items-start gap-3 rounded-xl border border-zinc-200 bg-white p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:border-accent hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900"
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent">{icon}</span>
      <span>
        <span className="block text-sm font-semibold text-zinc-900 dark:text-zinc-50">{title}</span>
        <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">{description}</span>
      </span>
    </Link>
  );
}

const linkClass = "flex items-center gap-1 text-xs font-medium text-accent hover:underline";

/**
 * The signed-in home (корекции.docx §64): start something new, pick up a recent
 * document, reuse a template, fetch a recent export, and see this month's usage.
 */
export function Dashboard() {
  const { data: user } = useCurrentUser();
  const documents = useDocumentList({ limit: 6 });
  const templates = useTemplates();
  const exports = useRecentExports(5);
  const usage = useUsage();
  const billing = useBilling();
  const documentLimit = billing.data?.usage.documents.limit;
  const aiLimit = billing.data?.usage.aiOperations.limit;
  const ownTemplates = (templates.data ?? []).filter((template) => !template.builtin);
  const suggested = [...(templates.data ?? [])].sort((a, b) => Number(b.isDefault) - Number(a.isDefault) || Number(a.builtin) - Number(b.builtin)).slice(0, 4);

  return (
    <div className="flex flex-1 flex-col bg-zinc-50 dark:bg-black">
      <AppHeader />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          {user?.fullName ? `Welcome back, ${user.fullName}` : "Welcome back"}
        </h1>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">Turn messy text into a well-formatted document. Your content stays as it is.</p>

        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <QuickAction href="/new" icon={<ClipboardPaste className="h-4 w-4" aria-hidden="true" />} title="Paste text" description="Structure is found for you." />
          <QuickAction href="/new?mode=upload" icon={<Upload className="h-4 w-4" aria-hidden="true" />} title="Upload a file" description="Word, PDF or plain text." />
          <QuickAction href="/new?reference=1" icon={<FileSearch className="h-4 w-4" aria-hidden="true" />} title="Match a document" description="Copy the look of a Word file." />
          <QuickAction href="/templates" icon={<LayoutTemplate className="h-4 w-4" aria-hidden="true" />} title="Templates" description="Browse, edit or make your own." />
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
          <div className="flex min-w-0 flex-col gap-6">
            <Card
              title="Recent documents"
              action={
                <Link href="/documents" className={linkClass}>
                  All documents <ArrowRight className="h-3 w-3" aria-hidden="true" />
                </Link>
              }
            >
              {documents.isPending ? (
                <Loading />
              ) : documents.error ? (
                <p className="text-sm text-red-600 dark:text-red-400">{errorMessage(documents.error)}</p>
              ) : documents.data.items.length === 0 ? (
                <p className="text-sm text-zinc-500 dark:text-zinc-400">No documents yet. Start with one of the options above.</p>
              ) : (
                <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
                  {documents.data.items.map((document) => (
                    <li key={document.id} className="flex items-center justify-between gap-3 py-2.5">
                      <Link href={`/documents/${document.id}`} className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-zinc-900 hover:text-accent dark:text-zinc-50">{document.title}</span>
                        <span className="block text-xs text-zinc-500 dark:text-zinc-400" title={formatDateTime(document.updatedAt)}>
                          Changed {formatWhen(document.updatedAt)}
                        </span>
                      </Link>
                      <StatusBadge document={document} />
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card
              title="Templates"
              action={
                <Link href="/templates" className={linkClass}>
                  Template library <ArrowRight className="h-3 w-3" aria-hidden="true" />
                </Link>
              }
            >
              {templates.isPending ? (
                <Loading />
              ) : (
                <>
                  <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
                    {ownTemplates.length === 0 ? "No templates of your own yet." : `${ownTemplates.length} of your own.`}
                  </p>
                  <ul className="grid gap-2 sm:grid-cols-2">
                    {suggested.map((template) => (
                      <li key={template.id} className="flex items-center justify-between gap-2 rounded-lg border border-zinc-200 px-3 py-2 dark:border-zinc-800">
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-zinc-800 dark:text-zinc-200">{template.name}</span>
                          <span className="text-xs text-zinc-500 dark:text-zinc-400">
                            {template.isDefault ? "Default" : template.builtin ? "Built-in" : "Yours"}
                          </span>
                        </span>
                        <Link href={`/new?template=${encodeURIComponent(template.id)}`} className="shrink-0 text-xs font-medium text-accent hover:underline">
                          Use
                        </Link>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </Card>
          </div>

          <div className="flex min-w-0 flex-col gap-6">
            <Card
              title={usage.data ? `Usage in ${monthFormat.format(new Date(usage.data.periodStart))}` : "Usage this month"}
              action={
                <Link href="/settings/billing" className={linkClass}>
                  {billing.data ? `${billing.data.plan.name} plan` : "Plan"} <ArrowRight className="h-3 w-3" aria-hidden="true" />
                </Link>
              }
            >
              {usage.isPending ? (
                <Loading />
              ) : usage.error ? (
                <p className="text-sm text-red-600 dark:text-red-400">{errorMessage(usage.error)}</p>
              ) : (
                <dl className="grid grid-cols-2 gap-3 text-sm">
                  {[
                    ["Documents created", usage.data.documentsCreated],
                    ["Exports", usage.data.exports],
                    ["AI operations", usage.data.aiOperations],
                    ["Processing jobs", usage.data.processingJobs],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-lg bg-zinc-50 px-3 py-2 dark:bg-zinc-950">
                      <dt className="text-xs text-zinc-500 dark:text-zinc-400">{label}</dt>
                      <dd className="text-lg font-semibold text-zinc-900 tabular-nums dark:text-zinc-50">{value}</dd>
                    </div>
                  ))}
                  <div className="col-span-2 text-xs text-zinc-500 dark:text-zinc-400">
                    Stored: {usage.data.documents}
                    {documentLimit != null ? ` of ${documentLimit}` : ""} document{usage.data.documents === 1 ? "" : "s"} · {formatBytes(usage.data.storageBytes)}
                    {aiLimit != null ? ` · ${usage.data.aiOperations} of ${aiLimit} AI operations` : ""}
                  </div>
                </dl>
              )}
            </Card>

            <Card title="Recent exports">
              {exports.isPending ? (
                <Loading />
              ) : exports.error ? (
                <p className="text-sm text-red-600 dark:text-red-400">{errorMessage(exports.error)}</p>
              ) : exports.data.length === 0 ? (
                <p className="text-sm text-zinc-500 dark:text-zinc-400">Nothing exported recently.</p>
              ) : (
                <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
                  {exports.data.map((job) => {
                    const result = job.result as ExportJobResult | null;
                    return (
                      <li key={job.id} className="flex items-center justify-between gap-3 py-2">
                        <span className="min-w-0">
                          <span className="block truncate text-sm text-zinc-800 dark:text-zinc-200">{result?.filename ?? "Export"}</span>
                          <span className="text-xs text-zinc-500 dark:text-zinc-400">{job.finishedAt ? formatWhen(job.finishedAt) : ""}</span>
                        </span>
                        {result && !result.expired ? (
                          <a href={jobFileUrl(job.id)} className="flex shrink-0 items-center gap-1 text-xs font-medium text-accent hover:underline">
                            <Download className="h-3.5 w-3.5" aria-hidden="true" /> Download
                          </a>
                        ) : (
                          <span className="shrink-0 text-xs text-zinc-400" title="Export files are kept for a limited time; export again to get a new one">
                            Expired
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </Card>
          </div>
        </div>
      </main>
    </div>
  );
}
