"use client";

import { ClipboardPaste, FileCode2, FileText, FileType2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { formatDateTime, formatRelative } from "@/i18n/format";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages/en";
import { thumbnailUrl } from "@/services/api";
import type { DocumentSummary } from "@/types/document";

type SourceKey = keyof Messages["dashboard"]["source"];

/** Where a project came from: its fallback picture's icon and tint (no content is invented); the Projects
 * gallery's cards use the same. */
export const SOURCE_LOOK: Record<SourceKey, { icon: typeof FileText; tile: string }> = {
  pasted_text: { icon: ClipboardPaste, tile: "bg-tile-blue text-tile-blue-ink" },
  uploaded_docx: { icon: FileType2, tile: "bg-tile-violet text-tile-violet-ink" },
  uploaded_pdf: { icon: FileText, tile: "bg-tile-rose text-tile-rose-ink" },
  uploaded_txt: { icon: FileText, tile: "bg-tile-teal text-tile-teal-ink" },
  uploaded_md: { icon: FileCode2, tile: "bg-tile-amber text-tile-amber-ink" },
  other: { icon: FileText, tile: "bg-tile-blue text-tile-blue-ink" },
};

export function sourceKey(sourceType: string): SourceKey {
  return (["pasted_text", "uploaded_docx", "uploaded_pdf", "uploaded_txt", "uploaded_md"] as const).find((key) => key === sourceType) ?? "other";
}

type Picture = "loading" | "shown" | "missing";

/**
 * One project in the dashboard gallery, with its real first page (the API draws it once per
 * revision; the browser keeps each version). While that loads -- or if it can't be drawn -- the
 * card shows a quiet picture of its kind instead, never made-up content.
 */
export function ProjectCard({ project }: { project: DocumentSummary }) {
  const { m, locale } = useI18n();
  const [picture, setPicture] = useState<Picture>("loading");
  const source = sourceKey(project.sourceType);
  const look = SOURCE_LOOK[source];
  const Icon = look.icon;
  const formatted = project.status !== "draft";

  return (
    <Link
      href={`/documents/${project.id}`}
      className="group flex h-full flex-col overflow-hidden rounded-2xl border border-line bg-surface transition-[box-shadow,transform,border-color] hover:-translate-y-0.5 hover:border-line-strong hover:shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      <div className="relative aspect-[4/3] overflow-hidden border-b border-line bg-surface-muted">
        {picture !== "shown" && (
          <div aria-hidden="true" data-testid="thumbnail-fallback" className="absolute inset-0 flex flex-col items-center justify-center gap-2">
            <span className={`flex h-12 w-12 items-center justify-center rounded-2xl ${look.tile} ${picture === "loading" ? "animate-pulse" : ""}`}>
              <Icon className="h-6 w-6" />
            </span>
          </div>
        )}
        {picture !== "missing" && (
          // eslint-disable-next-line @next/next/no-img-element -- an API picture behind the session cookie, not a static asset for next/image
          <img
            src={thumbnailUrl(project.id, project.updatedAt)}
            alt={format(m.dashboard.thumbnailAlt, { title: project.title })}
            loading="lazy"
            decoding="async"
            onLoad={() => setPicture("shown")}
            onError={() => setPicture("missing")}
            className={`absolute inset-0 h-full w-full bg-white object-cover object-top transition-opacity duration-300 ${picture === "shown" ? "opacity-100" : "opacity-0"}`}
          />
        )}
      </div>
      <div className="flex flex-1 flex-col gap-1 p-4">
        <span className="truncate text-sm font-semibold text-foreground group-hover:text-accent">{project.title}</span>
        <span className="flex items-center gap-1.5 truncate text-xs text-muted">
          <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {m.dashboard.kind.document} · {m.dashboard.source[source]}
        </span>
        <span className="mt-auto flex flex-wrap items-center justify-between gap-x-2 gap-y-1 pt-2">
          <span className="text-xs text-muted" title={formatDateTime(project.updatedAt, locale)}>
            {format(m.dashboard.edited, { when: formatRelative(project.updatedAt, locale) })}
          </span>
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${formatted ? "bg-accent-soft text-accent" : "bg-surface-muted text-muted"}`}
            title={formatted && project.templateName ? project.templateName : undefined}
          >
            {formatted ? m.dashboard.formatted : m.dashboard.draft}
          </span>
        </span>
      </div>
    </Link>
  );
}
