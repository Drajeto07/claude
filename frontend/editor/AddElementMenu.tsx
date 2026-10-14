"use client";

import { Heading1, List, Pilcrow, Table2 } from "lucide-react";
import { useState } from "react";

import { useI18n } from "@/i18n/I18nProvider";

export type InsertableType = "paragraph" | "heading" | "list" | "table";

const OPTIONS: { type: InsertableType; icon: typeof Pilcrow }[] = [
  { type: "paragraph", icon: Pilcrow },
  { type: "heading", icon: Heading1 },
  { type: "list", icon: List },
  { type: "table", icon: Table2 },
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
  const { m } = useI18n();
  const t = m.edBars;
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        aria-expanded={open}
        className="rounded-full border border-line px-3 py-1.5 text-xs font-medium text-foreground hover:border-line-strong hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50"
      >
        {t.addElement}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute bottom-full right-0 z-50 mb-2 w-44 rounded-xl border border-line bg-surface p-1.5 shadow-pop">
            {OPTIONS.map(({ type, icon: Icon }) => (
              <button
                key={type}
                type="button"
                onClick={() => {
                  setOpen(false);
                  onAdd(type);
                }}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm text-foreground hover:bg-surface-muted"
              >
                <Icon className="h-4 w-4 shrink-0 text-muted" aria-hidden="true" />
                {t.elements[type]}
              </button>
            ))}
            <div title={t.imageLater} className="flex w-full cursor-not-allowed items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm text-muted">
              <span className="h-4 w-4 shrink-0" aria-hidden="true" />
              {t.image}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
