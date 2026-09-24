"use client";

import { History, RotateCcw } from "lucide-react";

import type { TemplateVersion } from "@/types/document";

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

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
  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-zinc-900 dark:text-zinc-50">
        <History className="h-4 w-4 text-zinc-400" aria-hidden="true" />
        History
      </h2>
      {versions.length === 0 ? (
        <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">No saved versions yet.</p>
      ) : (
        <ol className="mt-3 flex flex-col divide-y divide-zinc-100 dark:divide-zinc-800">
          {versions.map((version) => (
            <li key={version.number} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="min-w-0">
                <span className="block truncate font-medium text-zinc-800 dark:text-zinc-200">
                  v{version.number} · {version.name}
                  {version.current && <span className="ml-2 rounded-full bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent">current</span>}
                </span>
                <span className="block text-xs text-zinc-500 dark:text-zinc-400">
                  {dateFormat.format(new Date(version.createdAt))}
                  {version.author && ` · ${version.author}`}
                </span>
              </span>
              {canRestore && !version.current && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onRestore(version.number)}
                  className="flex shrink-0 items-center gap-1 rounded-full border border-zinc-300 px-2.5 py-1 text-xs font-medium text-zinc-700 transition-colors hover:border-accent hover:text-accent disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300"
                >
                  <RotateCcw className="h-3 w-3" aria-hidden="true" />
                  Restore
                </button>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
