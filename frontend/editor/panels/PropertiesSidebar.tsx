"use client";

import { X } from "lucide-react";
import { useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { PropertiesPanel } from "@/editor/panels/PropertiesPanel";

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
function ResolvedStylesView() {
  const { document, selection } = useDocumentEditor();
  const element = selection.selectedElement;
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

/**
 * The Properties sidebar. On wide screens it is a column beside the pages; below
 * 1100 px it would squeeze them, so it opens over them instead, from the
 * toolbar's Properties button (`open`), and closes with `onClose`.
 */
export function PropertiesSidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("edit");

  return (
    <aside
      aria-label="Properties"
      className={`${open ? "flex" : "hidden"} absolute inset-y-0 right-0 z-30 w-80 max-w-[85vw] flex-col border-l border-zinc-200 bg-white shadow-xl min-[1100px]:static min-[1100px]:flex min-[1100px]:max-w-none min-[1100px]:shrink-0 min-[1100px]:shadow-none dark:border-zinc-800 dark:bg-zinc-950`}
    >
      <div className="flex border-b border-zinc-200 dark:border-zinc-800">
        <button type="button" onClick={() => setTab("edit")} className={tabClass(tab === "edit")}>
          Редактиране
        </button>
        <button type="button" onClick={() => setTab("styles")} className={tabClass(tab === "styles")}>
          Стилове
        </button>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close properties"
          className="px-3 text-zinc-400 hover:text-zinc-700 min-[1100px]:hidden dark:hover:text-zinc-200"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">{tab === "edit" ? <PropertiesPanel /> : <ResolvedStylesView />}</div>
    </aside>
  );
}
