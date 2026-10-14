"use client";

import { ArrowRight, CheckCircle2, ClipboardPaste, Clock3, Download, Languages, LayoutTemplate, Plus, Search, Sparkles, Upload } from "lucide-react";
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

const textLink = "inline-flex items-center gap-1 whitespace-nowrap rounded text-xs font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

export function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

/** A quick start: a tinted icon tile per action, so each is told apart at a glance. */
function QuickAction({ href, icon, tile, title, text, badge }: { href: string; icon: ReactNode; tile: string; title: string; text: string; badge?: string }) {
  return (
    <Link
      href={href}
      className="group flex items-start gap-3 rounded-2xl border border-line bg-surface p-4 transition-[box-shadow,transform,border-color] hover:-translate-y-0.5 hover:border-line-strong hover:shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${tile}`}>{icon}</span>
      <span className="min-w-0">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-semibold text-foreground">
          {title}
          {badge && <span className="rounded-full bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-muted">{badge}</span>}
        </span>
        <span className="mt-0.5 block text-xs text-muted">{text}</span>
      </span>
    </Link>
  );
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
          <div key={key} className="h-64 animate-pulse rounded-2xl border border-line bg-surface" />
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
      <p className="rounded-2xl border border-dashed border-line-strong px-6 py-10 text-center text-sm text-muted">{format(m.dashboard.noMatch, { query })}</p>
    ) : (
      <div className="flex flex-col items-center gap-4 rounded-2xl border border-dashed border-line-strong px-6 py-12 text-center">
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
        <h2 id="recent-projects" className="text-lg font-semibold tracking-tight text-foreground">
          {m.dashboard.recent}
        </h2>
        {/* A row of its own on a phone, so the search field keeps a usable width. */}
        <div className="flex w-full items-center gap-4 sm:w-auto sm:flex-1 sm:justify-end">
          <label className="relative min-w-0 flex-1 sm:max-w-xs">
            <span className="sr-only">{m.dashboard.searchLabel}</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden="true" />
            <input type="search" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={m.dashboard.searchPlaceholder} className={`${fieldClasses} h-10 pl-9`} />
          </label>
          <Link href="/documents" className={`${textLink} shrink-0 whitespace-nowrap`}>
            {m.dashboard.allProjects} <ArrowRight className="h-3 w-3" aria-hidden="true" />
          </Link>
        </div>
      </div>
      {body}
    </section>
  );
}

/** "What do you want to create?" -- and, plainly, what it does today and what comes later. */
function IdeaPanel() {
  const { m } = useI18n();
  const router = useRouter();
  const [text, setText] = useState("");

  function start(event: FormEvent) {
    event.preventDefault();
    const description = text.trim();
    router.push(description ? `/projects/new?describe=${encodeURIComponent(description)}` : "/projects/new");
  }

  return (
    <form onSubmit={start} className="rounded-2xl border border-line bg-surface p-5 shadow-card sm:p-6">
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-tile-violet text-tile-violet-ink">
          <Sparkles className="h-5 w-5" aria-hidden="true" />
        </span>
        <label htmlFor="describe-project" className="text-base font-semibold text-foreground">
          {m.dashboard.describeLabel}
        </label>
      </div>
      {/* Under the label from sm up; the full card width on a phone, so the field keeps its size. */}
      <div className="mt-3 sm:pl-13">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input id="describe-project" value={text} onChange={(e) => setText(e.target.value)} placeholder={m.dashboard.describePlaceholder} maxLength={300} className={`${fieldClasses} w-full sm:flex-1`} />
          <Button type="submit" size="lg" className="shrink-0">
            {m.dashboard.describeSubmit}
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
        <ul className="mt-3 flex flex-col gap-1.5 text-xs sm:flex-row sm:gap-5">
          <li className="flex items-center gap-1.5 text-foreground">
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" aria-hidden="true" />
            {m.dashboard.ideaNow}
          </li>
          <li className="flex items-center gap-1.5 text-muted">
            <Clock3 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            {m.dashboard.ideaNext}
          </li>
        </ul>
      </div>
    </form>
  );
}

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5 py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

/** Plan, recent exports and templates: kept, but quiet -- one light card beside the projects. */
function AtAGlance() {
  const { m, locale } = useI18n();
  const usage = useUsage();
  const billing = useBilling();
  const exports = useRecentExports(5);
  const templates = useTemplates();
  const documentLimit = billing.data?.usage.documents.limit;
  const aiLimit = billing.data?.usage.aiOperations.limit;
  const suggested = [...(templates.data ?? [])].sort((a, b) => Number(b.isDefault) - Number(a.isDefault) || Number(a.builtin) - Number(b.builtin)).slice(0, 4);
  const used = usage.data?.documents ?? 0;
  const share = documentLimit ? Math.min(100, Math.round((used / documentLimit) * 100)) : 0;

  return (
    <aside aria-label={m.dashboard.glance} className="flex h-fit flex-col divide-y divide-line rounded-2xl border border-line bg-surface p-5">
      <Section
        title={m.dashboard.plan}
        action={
          <Link href="/settings/billing" className={textLink}>
            {billing.data ? format(m.dashboard.planLink, { plan: billing.data.plan.name }) : m.shell.billing} <ArrowRight className="h-3 w-3" aria-hidden="true" />
          </Link>
        }
      >
        {usage.isPending ? (
          <p className="text-sm text-muted">{m.common.loading}</p>
        ) : usage.isError ? (
          <p className="text-sm text-muted">{m.dashboard.loadError}</p>
        ) : (
          <div className="flex flex-col gap-2 text-sm text-foreground">
            <p>{documentLimit != null ? format(m.dashboard.usageDocuments, { used, limit: documentLimit }) : format(m.dashboard.usageDocumentsUnlimited, { used })}</p>
            {documentLimit != null && (
              <div role="meter" aria-label={m.dashboard.plan} aria-valuemin={0} aria-valuemax={documentLimit} aria-valuenow={used} className="h-1.5 overflow-hidden rounded-full bg-surface-muted">
                <div className="h-full rounded-full bg-accent" style={{ width: `${share}%` }} />
              </div>
            )}
            {aiLimit != null && <p className="text-xs text-muted">{format(m.dashboard.usageAi, { used: usage.data.aiOperations, limit: aiLimit })}</p>}
            <p className="text-xs text-muted">{format(m.dashboard.usageExports, { count: usage.data.exports })}</p>
          </div>
        )}
      </Section>

      <Section title={m.dashboard.exports}>
        {exports.isPending ? (
          <p className="text-sm text-muted">{m.common.loading}</p>
        ) : exports.isError || exports.data.length === 0 ? (
          <p className="text-sm text-muted">{m.dashboard.noExports}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {exports.data.map((job) => {
              const result = job.result as ExportJobResult | null;
              return (
                <li key={job.id} className="flex items-center justify-between gap-3">
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-foreground">{result?.filename ?? "—"}</span>
                    <span className="text-xs text-muted">{job.finishedAt ? formatRelative(job.finishedAt, locale) : ""}</span>
                  </span>
                  {result && !result.expired ? (
                    <a href={jobFileUrl(job.id)} className={textLink}>
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
      </Section>

      <Section
        title={m.dashboard.templatesTitle}
        action={
          <Link href="/templates" className={textLink}>
            {m.dashboard.templateLibrary} <ArrowRight className="h-3 w-3" aria-hidden="true" />
          </Link>
        }
      >
        {templates.isPending ? (
          <p className="text-sm text-muted">{m.common.loading}</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {suggested.map((template) => (
              <li key={template.id} className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 hover:bg-surface-muted">
                <span className="flex min-w-0 items-center gap-2 text-sm text-foreground">
                  <LayoutTemplate className="h-3.5 w-3.5 shrink-0 text-muted" aria-hidden="true" />
                  <span className="truncate">{template.name}</span>
                </span>
                <Link href={`/new?template=${encodeURIComponent(template.id)}`} className={textLink}>
                  {m.dashboard.useTemplate}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </aside>
  );
}

/**
 * Screen 2 of SmartDoc 2.0 (S2-014, refined after the owner's UI review of 2026-10-14): start
 * something -- from an idea or a quick start, Translate among them -- then find and resume a
 * project; the plan, exports and templates stay in a quiet column beside it.
 */
export function Dashboard() {
  const { m } = useI18n();
  const { data: user } = useCurrentUser();
  const actions = m.dashboard.actions;

  return (
    <AppShell>
      <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-8 px-4 py-8 sm:px-8 lg:py-10">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-foreground">
              {user?.fullName ? format(m.dashboard.welcomeName, { name: user.fullName }) : m.dashboard.welcome}
            </h1>
            <p className="mt-1.5 text-sm text-muted">{m.dashboard.subtitle}</p>
          </div>
          <Link href="/projects/new" className={`${buttonClasses({ size: "lg" })} hidden sm:inline-flex`}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            {m.shell.createProject}
          </Link>
        </header>
        {user && !user.emailVerified && <VerifyEmailBanner email={user.email} />}

        <IdeaPanel />

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
          <QuickAction href="/projects/new" tile="bg-tile-violet text-tile-violet-ink" icon={<Plus className="h-5 w-5" aria-hidden="true" />} title={actions.newProject.title} text={actions.newProject.text} />
          <QuickAction href="/new" tile="bg-tile-blue text-tile-blue-ink" icon={<ClipboardPaste className="h-5 w-5" aria-hidden="true" />} title={actions.paste.title} text={actions.paste.text} />
          <QuickAction href="/new?mode=upload" tile="bg-tile-teal text-tile-teal-ink" icon={<Upload className="h-5 w-5" aria-hidden="true" />} title={actions.upload.title} text={actions.upload.text} />
          <QuickAction href="/translate" tile="bg-tile-rose text-tile-rose-ink" icon={<Languages className="h-5 w-5" aria-hidden="true" />} title={actions.translate.title} text={actions.translate.text} badge={m.common.comingSoon} />
          <QuickAction href="/templates" tile="bg-tile-amber text-tile-amber-ink" icon={<LayoutTemplate className="h-5 w-5" aria-hidden="true" />} title={actions.templates.title} text={actions.templates.text} />
        </div>

        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,18rem)]">
          <Projects />
          <AtAGlance />
        </div>
      </main>
    </AppShell>
  );
}
