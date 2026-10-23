"use client";

import { Heading1, ImagePlus, List, Pilcrow, Table2 } from "lucide-react";
import { useRef, useState } from "react";

import { ImageFileInput } from "@/editor/ImageFileInput";
import { useI18n } from "@/i18n/I18nProvider";

export type InsertableType = "paragraph" | "heading" | "list" | "table";

const OPTIONS: { type: InsertableType; icon: typeof Pilcrow }[] = [
  { type: "paragraph", icon: Pilcrow },
  { type: "heading", icon: Heading1 },
  { type: "list", icon: List },
  { type: "table", icon: Table2 },
];

/**
 * Manual (non-AI) element insertion -- Stage 10. Inserts after the currently
 * selected element (or at the end if nothing is selected), matching the
 * existing New-page button's own placement rule. A picture (S2-130) is picked
 * from the device first: `onAddImage` gets the files (editor/imageFiles.ts).
 */
export function AddElementMenu({
  onAdd,
  onAddImage,
  disabled,
}: {
  onAdd: (type: InsertableType) => void;
  onAddImage?: (files: File[]) => void;
  disabled?: boolean;
}) {
  const { m } = useI18n();
  const t = m.edBars;
  const [open, setOpen] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

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
            {onAddImage && (
              <button
                type="button"
                title={t.imageHint}
                onClick={() => {
                  setOpen(false);
                  picker.current?.click();
                }}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm text-foreground hover:bg-surface-muted"
              >
                <ImagePlus className="h-4 w-4 shrink-0 text-muted" aria-hidden="true" />
                {t.image}
              </button>
            )}
          </div>
        </>
      )}
      {onAddImage && <ImageFileInput ref={picker} onFiles={onAddImage} />}
    </div>
  );
}
