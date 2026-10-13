"use client";

import { ArrowRight, ClipboardPaste, Download, LayoutTemplate, Plus, Search, Sparkles, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { ProjectCard } from "@/components/dashboard/ProjectCard";
import { AppShell } from "@/components/shell/AppShell";
import { Button, buttonClasses } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { fieldClasses } from "@/components/ui/TextField";
import { VerifyEmailBanner } from "@/components/VerifyEmail";
import { formatRelative } from "@/i18n/format";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import { jobFileUrl } from "@/services/api";
import { useBilling, useCurrentUser, useDocumentList, useRecentExports, useTemplates, useUsage } from "@/services/queries";
import type { ExportJobResult } from "@/types/document";

/** How long typing pauses before the gallery searches (one request per pause, not per key). */
const SEARCH_PAUSE_MS = 250;
const GALLERY_SIZE = 9;

function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-surface p-5 shadow-sm">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

const panelLink = "flex items-center gap-1 rounded text-xs font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

function QuickAction({ href, icon, title, text }: { href: string; icon: ReactNode; title: string; text: string }) {
  return (
    <Link
      href={href}
      className="group flex items-start gap-3 rounded-2xl border border-line bg-surface p-4 shadow-sm transition-[box-shadow,transform,border-color] hover:-translate-y-0.5 hover:border-accent/40 hover:shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-accent">{icon}</span>
      <span>
        <span className="block text-sm font-semibold text-foreground">{title}</span>
        <span className="mt-0.5 block text-xs text-muted">{text}</span>
      </span>
    </Link>
  );
}

export function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

function Projects() {
  const { m } = useI18n();
  const [typed, setTyped] = useState("");
  const query = useDebounced(typed.trim(), SEARCH_PAUSE_MS);
  const projects = useDocumentList({ q: query || undefined, limit: GALLERY_SIZE });

  let body: ReactNode;
  if (projects.isPending) {
    body = (
      <div aria-busy="true" className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
        <span className="sr-only">{m.dashboard.loadingProjects}</span>
        {[0, 1, 2].map((key) => (
          <div key={key} className="h-56 animate-pulse rounded-2xl border border-line bg-surface" />
        ))}
      </div>
    );
  } else if (projects.isError) {
    body = (
      <div className="flex flex-col items-start gap-3">
        <Notice tone="error">{m.dashboard.loadError}</Notice>
        <Button variant="secondary" size="sm" onClick={() => void projects.refetch()}>
          {m.common.tryAgain}
        </Button>
      </div>
    );
  } else if (projects.data.items.length === 0) {
    body = query ? (
      <p className="rounded-2xl border border-dashed border-line px-6 py-10 text-center text-sm text-muted">{format(m.dashboard.noMatch, { query })}</p>
    ) : (
      <div className="flex flex-col items-center gap-4 rounded-2xl border border-dashed border-line px-6 py-12 text-center">
        <p className="text-sm text-muted">{m.dashboard.empty}</p>
        <Link href="/projects/new" className={buttonClasses()}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          {m.dashboard.emptyCta}
        </Link>
      </div>
    );
  } else {
    body = (
      <ul className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
        {projects.data.items.map((project) => (
          <li key={project.id}>
            <ProjectCard project={project} />
          </li>
        ))}
      </ul>
    );
  }

  return (
    <section aria-labelledby="recent-projects" className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="recent-projects" className="text-base font-semibold text-foreground">
          {m.dashboard.recent}
        </h2>
        <div className="flex flex-1 items-center justify-end gap-3">
          <label className="relative w-full max-w-xs">
            <span className="sr-only">{m.dashboard.searchLabel}</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden="true" />
            <input type="search" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={m.dashboard.searchPlaceholder} className={`${fieldClasses} h-10 pl-9`} />
          </label>
          <Link href="/documents" className={`${panelLink} whitespace-nowrap`}>
            {m.dashboard.allProjects} <ArrowRight className="h-3 w-3" aria-hidden="true" />
          </Link>
        </div>
      </div>
      {body}
    </section>
  );
}

function Describe() {
  const { m } = useI18n();
  const router = useRouter();
  const [text, setText] = useState("");

  function start(event: FormEvent) {
    event.preventDefault();
    const description = text.trim();
    router.push(description ? `/projects/new?describe=${encodeURIComponent(description)}` : "/projects/new");
  }

  return (
    <form onSubmit={start} className="relative overflow-hidden rounded-2xl border border-accent/15 bg-gradient-to-r from-indigo-50 via-surface to-violet-50 p-5 shadow-sm sm:p-6">
      <label htmlFor="describe-project" className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <Sparkles className="h-4 w-4 text-brand-purple" aria-hidden="true" />
        {m.dashboard.describeLabel}
      </label>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input id="describe-project" value={text} onChange={(e) => setText(e.target.value)} placeholder={m.dashboard.describePlaceholder} maxLength={300} className={`${fieldClasses} flex-1`} />
        <Button type="submit" size="lg" className="shrink-0">
          {m.dashboard.describeSubmit}
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>
    </form>
  );
}

function SidePanels() {
  const { m, locale } = useI18n();
  const usage = useUsage();
  const billing = useBilling();
  const exports = useRecentExports(5);
  const templates = useTemplates();
  const documentLimit = billing.data?.usage.documents.limit;
  const aiLimit = billing.data?.usage.aiOperations.limit;
  const suggested = [...(templates.data ?? [])].sort((a, b) => Number(b.isDefault) - Number(a.isDefault) || Number(a.builtin) - Number(b.builtin)).slice(0, 4);

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <Panel
        title={m.dashboard.plan}
        action={
          <Link href="/settings/billing" className={panelLink}>
            {billing.data ? format(m.dashboard.planLink, { plan: billing.data.plan.name }) : m.shell.billing} <ArrowRight className="h-3 w-3" aria-hidden="true" />
          </Link>
        }
      >
        {usage.isPending ? (
          <p className="text-sm text-muted">{m.common.loading}</p>
        ) : usage.isError ? (
          <Notice tone="error">{m.dashboard.loadError}</Notice>
        ) : (
          <ul className="space-y-1.5 text-sm text-foreground">
            <li>{documentLimit != null ? format(m.dashboard.usageDocuments, { used: usage.data.documents, limit: documentLimit }) : format(m.dashboard.usageDocumentsUnlimited, { used: usage.data.documents })}</li>
            {aiLimit != null && <li>{format(m.dashboard.usageAi, { used: usage.data.aiOperations, limit: aiLimit })}</li>}
            <li className="text-muted">{format(m.dashboard.usageExports, { count: usage.data.exports })}</li>
          </ul>
        )}
      </Panel>

      <Panel title={m.dashboard.exports}>
        {exports.isPending ? (
          <p className="text-sm text-muted">{m.common.loading}</p>
        ) : exports.isError || exports.data.length === 0 ? (
          <p className="text-sm text-muted">{m.dashboard.noExports}</p>
        ) : (
          <ul className="divide-y divide-line">
            {exports.data.map((job) => {
              const result = job.result as ExportJobResult | null;
              return (
                <li key={job.id} className="flex items-center justify-between gap-3 py-2">
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-foreground">{result?.filename ?? "—"}</span>
                    <span className="text-xs text-muted">{job.finishedAt ? formatRelative(job.finishedAt, locale) : ""}</span>
                  </span>
                  {result && !result.expired ? (
                    <a href={jobFileUrl(job.id)} className={panelLink}>
                      <Download className="h-3.5 w-3.5" aria-hidden="true" /> {m.dashboard.download}
                    </a>
                  ) : (
                    <span className="shrink-0 text-xs text-muted" title={m.dashboard.expiredHint}>
                      {m.dashboard.expired}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Panel>

      <Panel
        title={m.dashboard.templatesTitle}
        action={
          <Link href="/templates" className={panelLink}>
            {m.dashboard.templateLibrary} <ArrowRight className="h-3 w-3" aria-hidden="true" />
          </Link>
        }
      >
        {templates.isPending ? (
          <p className="text-sm text-muted">{m.common.loading}</p>
        ) : (
          <ul className="space-y-2">
            {suggested.map((template) => (
              <li key={template.id} className="flex items-center justify-between gap-2 rounded-xl border border-line px-3 py-2">
                <span className="min-w-0 truncate text-sm text-foreground">{template.name}</span>
                <Link href={`/new?template=${encodeURIComponent(template.id)}`} className={panelLink}>
                  {m.dashboard.useTemplate}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

/**
 * Screen 2 of SmartDoc 2.0 (S2-014): say what to make or pick a quick start, find and resume a
 * project, and keep an eye on the plan, recent exports and templates.
 */
export function Dashboard() {
  const { m } = useI18n();
  const { data: user } = useCurrentUser();

  return (
    <AppShell>
      <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 px-4 py-8 sm:px-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            {user?.fullName ? format(m.dashboard.welcomeName, { name: user.fullName }) : m.dashboard.welcome}
          </h1>
          <p className="mt-1 text-sm text-muted">{m.dashboard.subtitle}</p>
          {user && !user.emailVerified && <VerifyEmailBanner email={user.email} />}
        </header>

        <Describe />

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <QuickAction href="/projects/new" icon={<Plus className="h-5 w-5" aria-hidden="true" />} title={m.dashboard.actions.newProject.title} text={m.dashboard.actions.newProject.text} />
          <QuickAction href="/new" icon={<ClipboardPaste className="h-5 w-5" aria-hidden="true" />} title={m.dashboard.actions.paste.title} text={m.dashboard.actions.paste.text} />
          <QuickAction href="/new?mode=upload" icon={<Upload className="h-5 w-5" aria-hidden="true" />} title={m.dashboard.actions.upload.title} text={m.dashboard.actions.upload.text} />
          <QuickAction href="/templates" icon={<LayoutTemplate className="h-5 w-5" aria-hidden="true" />} title={m.dashboard.actions.templates.title} text={m.dashboard.actions.templates.text} />
        </div>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
          <Projects />
          <SidePanels />
        </div>
      </main>
    </AppShell>
  );
}
