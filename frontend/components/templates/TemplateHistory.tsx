"use client";

import { History, RotateCcw } from "lucide-react";

import { formatDateTime } from "@/i18n/format";
import { useI18n } from "@/i18n/I18nProvider";
import type { TemplateVersion } from "@/types/document";

/** Every saved version, newest first; restoring one saves it again as the newest. */
export function TemplateHistory({
  versions,
  canRestore,
  busy,
  onRestore,
}: {
  versions: TemplateVersion[];
  canRestore: boolean;
  busy: boolean;
  onRestore: (number: number) => void;
}) {
  const { m, locale } = useI18n();
  const t = m.templateEditor.history;
  return (
    <section className="rounded-2xl border border-line bg-surface p-4 shadow-card">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <History className="h-4 w-4 text-muted" aria-hidden="true" />
        {t.title}
      </h2>
      {versions.length === 0 ? (
        <p className="mt-2 text-sm text-muted">{t.none}</p>
      ) : (
        <ol className="mt-3 flex flex-col divide-y divide-line">
          {versions.map((version) => (
            <li key={version.number} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="min-w-0">
                <span className="block truncate font-medium text-foreground">
                  v{version.number} · {version.name}
                  {version.current && <span className="ml-2 rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent">{t.current}</span>}
                </span>
                <span className="block text-xs text-muted">
                  {formatDateTime(version.createdAt, locale)}
                  {version.author && ` · ${version.author}`}
                </span>
              </span>
              {canRestore && !version.current && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onRestore(version.number)}
                  className="flex shrink-0 items-center gap-1 rounded-full border border-line-strong px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:border-accent hover:text-accent disabled:opacity-50"
                >
                  <RotateCcw className="h-3 w-3" aria-hidden="true" />
                  {t.restore}
                </button>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
