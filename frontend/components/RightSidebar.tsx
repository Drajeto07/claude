"use client";

import { useState } from "react";

import { PropertiesPanel } from "@/components/PropertiesPanel";
import type { Document } from "@/types/document";

type Tab = "edit" | "styles";

function tabClass(active: boolean): string {
  return `flex-1 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${
    active ? "border-accent text-accent" : "border-transparent text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
  }`;
}

/** Read-only view of the selected element's fully resolved CSS -- template
 * + instructions + any override, all folded together -- as opposed to the
 * "Редактиране" tab's editable override controls. Genuinely different
 * information (what will actually render), not a cosmetic duplicate tab. */
function ResolvedStylesView({ document, selectedElementId }: { document: Document; selectedElementId: string | null }) {
  const element = document.elements.find((el) => el.id === selectedElementId) ?? null;
  if (!element) {
    return <p className="text-sm text-zinc-500 dark:text-zinc-400">Select an element to see its fully resolved style.</p>;
  }
  const css = element.styleRef ? (document.resolvedStyles[element.styleRef] ?? {}) : {};
  const entries = Object.entries(css);
  if (entries.length === 0) {
    return <p className="text-sm text-zinc-500 dark:text-zinc-400">No resolved styles yet -- apply a template or instructions first.</p>;
  }
  return (
    <dl className="flex flex-col gap-1.5 text-sm">
      {entries.map(([property, value]) => (
        <div key={property} className="flex items-center justify-between gap-3 border-b border-zinc-100 pb-1.5 dark:border-zinc-800">
          <dt className="font-mono text-xs text-zinc-500 dark:text-zinc-400">{property}</dt>
          <dd className="font-mono text-xs text-zinc-800 dark:text-zinc-200">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function RightSidebar({
  document,
  selectedElementId,
  onUpdated,
  onBeforeMutate,
}: {
  document: Document;
  selectedElementId: string | null;
  onUpdated: (updated: Document) => void;
  onBeforeMutate: () => Promise<unknown>;
}) {
  const [tab, setTab] = useState<Tab>("edit");

  return (
    <aside className="flex w-80 shrink-0 flex-col border-l border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex border-b border-zinc-200 dark:border-zinc-800">
        <button type="button" onClick={() => setTab("edit")} className={tabClass(tab === "edit")}>
          Редактиране
        </button>
        <button type="button" onClick={() => setTab("styles")} className={tabClass(tab === "styles")}>
          Стилове
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {tab === "edit" ? (
          <PropertiesPanel document={document} selectedElementId={selectedElementId} onUpdated={onUpdated} onBeforeMutate={onBeforeMutate} />
        ) : (
          <ResolvedStylesView document={document} selectedElementId={selectedElementId} />
        )}
      </div>
    </aside>
  );
}
