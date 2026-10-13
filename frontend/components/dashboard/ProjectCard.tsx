"use client";

import { FileText, FileType2, ClipboardPaste, FileCode2 } from "lucide-react";
import Link from "next/link";

import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import { formatDateTime, formatRelative } from "@/i18n/format";
import type { Messages } from "@/i18n/messages/en";
import type { DocumentSummary } from "@/types/document";

type SourceKey = keyof Messages["dashboard"]["source"];
const SOURCE_ICON: Partial<Record<SourceKey, typeof FileText>> = {
  pasted_text: ClipboardPaste,
  uploaded_docx: FileType2,
  uploaded_pdf: FileText,
  uploaded_md: FileCode2,
};

export function sourceKey(sourceType: string): SourceKey {
  return (["pasted_text", "uploaded_docx", "uploaded_pdf", "uploaded_txt", "uploaded_md"] as const).find((key) => key === sourceType) ?? "other";
}

/**
 * One project in the dashboard gallery. The picture is a drawn page for now -- a real preview of
 * the first page needs rendering it (S2-018) -- and the card says only what is known: kind,
 * where it came from, whether a template was applied, when it last changed.
 */
export function ProjectCard({ project }: { project: DocumentSummary }) {
  const { m, locale } = useI18n();
  const source = sourceKey(project.sourceType);
  const Icon = SOURCE_ICON[source] ?? FileText;
  const formatted = project.status !== "draft";
  return (
    <Link
      href={`/documents/${project.id}`}
      className="group flex flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-sm transition-[box-shadow,transform,border-color] hover:-translate-y-0.5 hover:border-accent/40 hover:shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      <div aria-hidden="true" className="relative flex aspect-[4/3] items-end justify-center bg-gradient-to-br from-indigo-50 via-surface-muted to-violet-50 px-6 pt-5">
        <div className="relative h-full w-3/5 rounded-t-lg border border-b-0 border-line bg-surface p-3 shadow-sm transition-transform group-hover:-translate-y-1">
          <div className="h-2 w-3/4 rounded-full bg-accent/30" />
          <div className="mt-2.5 space-y-1.5">
            <div className="h-1.5 w-full rounded-full bg-line" />
            <div className="h-1.5 w-11/12 rounded-full bg-line" />
            <div className="h-1.5 w-4/5 rounded-full bg-line" />
            <div className="h-1.5 w-10/12 rounded-full bg-line" />
          </div>
        </div>
        <span className="absolute left-3 top-3 flex h-8 w-8 items-center justify-center rounded-lg bg-surface/90 text-accent shadow-sm">
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className="flex flex-1 flex-col gap-1 p-4">
        <span className="truncate text-sm font-semibold text-foreground group-hover:text-accent">{project.title}</span>
        <span className="truncate text-xs text-muted">
          {m.dashboard.kind.document} · {m.dashboard.source[source]}
        </span>
        <span className="mt-2 flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
          <span className="text-xs text-muted" title={formatDateTime(project.updatedAt, locale)}>
            {format(m.dashboard.edited, { when: formatRelative(project.updatedAt, locale) })}
          </span>
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${formatted ? "bg-accent/10 text-accent" : "bg-surface-muted text-muted"}`}
            title={formatted && project.templateName ? project.templateName : undefined}
          >
            {formatted ? m.dashboard.formatted : m.dashboard.draft}
          </span>
        </span>
      </div>
    </Link>
  );
}
