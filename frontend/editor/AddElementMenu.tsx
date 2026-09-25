"use client";

import { Heading1, List, Pilcrow, Table2 } from "lucide-react";
import { useState } from "react";

export type InsertableType = "paragraph" | "heading" | "list" | "table";

const OPTIONS: { type: InsertableType; label: string; icon: typeof Pilcrow }[] = [
  { type: "paragraph", label: "Paragraph", icon: Pilcrow },
  { type: "heading", label: "Heading", icon: Heading1 },
  { type: "list", label: "List", icon: List },
  { type: "table", label: "Table", icon: Table2 },
];

/**
 * Manual (non-AI) element insertion -- Stage 10. Image is deliberately not
 * an option here: it needs a file picked first, a different UX shape
 * entirely, not a same-shape variant of "insert an empty one" like the
 * other four. Inserts after the currently selected element (or at the end
 * if nothing is selected), matching the existing New-page button's own
 * placement rule.
 */
export function AddElementMenu({ onAdd, disabled }: { onAdd: (type: InsertableType) => void; disabled?: boolean }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        className="rounded-full border border-zinc-200 px-3 py-1.5 text-xs font-medium text-zinc-600 hover:border-zinc-300 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-800 dark:text-zinc-400 dark:hover:border-zinc-700"
      >
        Добави елемент
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute bottom-full right-0 z-50 mb-2 w-44 rounded-lg border border-zinc-200 bg-white p-1.5 shadow-lg dark:border-zinc-800 dark:bg-zinc-900">
            {OPTIONS.map(({ type, label, icon: Icon }) => (
              <button
                key={type}
                type="button"
                onClick={() => {
                  setOpen(false);
                  onAdd(type);
                }}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
              >
                <Icon className="h-4 w-4 shrink-0 text-zinc-400" aria-hidden="true" />
                {label}
              </button>
            ))}
            <div
              title="Coming in a future update -- needs a file picker, not just an insert"
              className="flex w-full cursor-not-allowed items-center gap-2 rounded px-2 py-1.5 text-left text-sm text-zinc-400 dark:text-zinc-600"
            >
              <span className="h-4 w-4 shrink-0" aria-hidden="true" />
              Image
            </div>
          </div>
        </>
      )}
    </div>
  );
}
