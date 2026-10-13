"use client";

import {
  BookOpenCheck,
  FileSearch,
  FileText,
  Image as ImageIcon,
  LayoutTemplate,
  Mail,
  Newspaper,
  Presentation,
  Shapes,
  Sparkles,
  Upload,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { fieldClasses } from "@/components/ui/TextField";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";

import { PROJECT_TYPES, suggestProjectType, type ProjectType, type ProjectTypeId } from "./projectTypes";

const ICONS: Record<ProjectTypeId, typeof FileText> = {
  document: FileText,
  cv: UserRound,
  upload: Upload,
  template: LayoutTemplate,
  matchLook: FileSearch,
  presentation: Presentation,
  brochure: Newspaper,
  invitation: Mail,
  poster: ImageIcon,
  freeDesign: Shapes,
};

function TypeCard({ type, suggested }: { type: ProjectType; suggested: boolean }) {
  const { m } = useI18n();
  const Icon = ICONS[type.id];
  const copy = m.newProject.types[type.id];
  const ring = suggested ? "ring-2 ring-accent ring-offset-2 ring-offset-surface-muted" : "";
  const inner = (
    <>
      <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${type.href ? "bg-accent/10 text-accent" : "bg-surface-muted text-muted"}`}>
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <span className="min-w-0">
        <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
          {copy.title}
          {!type.href && <span className="rounded-full bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-muted">{m.common.comingSoon}</span>}
        </span>
        <span className="mt-0.5 block text-xs text-muted">{copy.text}</span>
      </span>
    </>
  );
  if (!type.href) {
    return (
      <div aria-disabled="true" data-suggested={suggested || undefined} className={`flex items-start gap-3 rounded-2xl border border-dashed border-line bg-surface/60 p-4 ${ring}`}>
        {inner}
      </div>
    );
  }
  return (
    <Link
      href={type.href}
      data-suggested={suggested || undefined}
      className={`group flex items-start gap-3 rounded-2xl border border-line bg-surface p-4 shadow-sm transition-[box-shadow,transform,border-color] hover:-translate-y-0.5 hover:border-accent/40 hover:shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${ring}`}
    >
      {inner}
    </Link>
  );
}

/**
 * Screen 3 of SmartDoc 2.0 (S2-015): choose what to make -- by hand, or by describing it and
 * taking the suggested type. Types that start today open the existing flows; the visual ones
 * are shown as coming with the canvas, not as working.
 */
export function NewProject() {
  const { m } = useI18n();
  const searchParams = useSearchParams();
  const [description, setDescription] = useState(searchParams.get("describe") ?? "");
  const suggestion = suggestProjectType(description);
  const available = PROJECT_TYPES.filter((type) => type.href);
  const later = PROJECT_TYPES.filter((type) => !type.href);

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-8 px-4 py-8 sm:px-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">{m.newProject.title}</h1>
        <p className="mt-1 text-sm text-muted">{m.newProject.subtitle}</p>
      </header>

      <section className="rounded-2xl border border-accent/15 bg-gradient-to-r from-indigo-50 via-surface to-violet-50 p-5 shadow-sm sm:p-6">
        <label htmlFor="project-description" className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Sparkles className="h-4 w-4 text-brand-purple" aria-hidden="true" />
          {m.newProject.describeLabel}
        </label>
        <input
          id="project-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={m.newProject.describePlaceholder}
          maxLength={300}
          className={`${fieldClasses} mt-3`}
        />
        {description.trim() && (
          <div role="status" className="mt-3 text-sm">
            {suggestion ? (
              <p className="flex items-center gap-2 font-medium text-foreground">
                <BookOpenCheck className="h-4 w-4 text-accent" aria-hidden="true" />
                {format(m.newProject.suggestion, { type: m.newProject.types[suggestion].title })}
              </p>
            ) : (
              <p className="text-muted">{m.newProject.noSuggestion}</p>
            )}
            <p className="mt-1 text-xs text-muted">{m.newProject.suggestionNote}</p>
          </div>
        )}
      </section>

      <section aria-labelledby="types-now" className="flex flex-col gap-3">
        <h2 id="types-now" className="text-base font-semibold text-foreground">
          {m.newProject.available}
        </h2>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {available.map((type) => (
            <li key={type.id}>
              <TypeCard type={type} suggested={type.id === suggestion} />
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="types-later" className="flex flex-col gap-3">
        <div>
          <h2 id="types-later" className="text-base font-semibold text-foreground">
            {m.newProject.later}
          </h2>
          <p className="mt-0.5 text-xs text-muted">{m.newProject.laterNote}</p>
        </div>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {later.map((type) => (
            <li key={type.id}>
              <TypeCard type={type} suggested={type.id === suggestion} />
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
