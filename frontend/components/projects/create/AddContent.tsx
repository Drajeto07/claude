"use client";

import { ClipboardPaste, Upload } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { fieldClasses } from "@/components/ui/TextField";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import type { PdfMode } from "@/types/document";

export type ContentInput =
  | { method: "paste"; text: string }
  | { method: "upload"; file: File; autolink: boolean; pdfMode: PdfMode };

function MethodButton({ selected, onSelect, icon, children }: { selected: boolean; onSelect: () => void; icon: ReactNode; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`flex h-11 flex-1 items-center justify-center gap-2 rounded-xl border text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
        selected ? "border-accent bg-accent-soft text-foreground" : "border-line bg-surface text-muted hover:text-foreground"
      }`}
    >
      {icon}
      {children}
    </button>
  );
}

/** Step 1: the content -- pasted, or a Word, PDF or text file. Nothing is sent until "Analyse". */
export function AddContent({ initialMethod, maxFileMb, onSubmit }: { initialMethod: "paste" | "upload"; maxFileMb?: number; onSubmit: (input: ContentInput) => void }) {
  const { m } = useI18n();
  const t = m.create.content;
  const [method, setMethod] = useState(initialMethod);
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [autolink, setAutolink] = useState(false);
  const [pdfMode, setPdfMode] = useState<PdfMode>("editable");
  const extension = file?.name.split(".").pop()?.toLowerCase();
  const ready = method === "paste" ? text.trim().length > 0 : file !== null;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    onSubmit(method === "paste" ? { method, text } : { method, file: file!, autolink: extension === "docx" && autolink, pdfMode: extension === "pdf" ? pdfMode : "editable" });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-5">
      <div className="flex gap-2">
        <MethodButton selected={method === "paste"} onSelect={() => setMethod("paste")} icon={<ClipboardPaste className="h-4 w-4" aria-hidden="true" />}>
          {t.paste}
        </MethodButton>
        <MethodButton selected={method === "upload"} onSelect={() => setMethod("upload")} icon={<Upload className="h-4 w-4" aria-hidden="true" />}>
          {t.upload}
        </MethodButton>
      </div>

      {method === "paste" ? (
        <label className="flex flex-col gap-1.5 text-sm font-medium text-foreground">
          {t.pasteLabel}
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={12} placeholder={t.pastePlaceholder} className={`${fieldClasses} h-auto py-3 font-normal leading-relaxed`} />
        </label>
      ) : (
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1.5 text-sm font-medium text-foreground">
            {t.fileLabel}
            <input
              type="file"
              accept=".txt,.docx,.pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className={`${fieldClasses} h-auto py-2 font-normal file:mr-3 file:rounded-lg file:border-0 file:bg-accent-soft file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-accent`}
            />
          </label>
          <p className="text-xs text-muted">
            {t.fileHint} {maxFileMb ? format(t.fileLimit, { mb: maxFileMb }) : ""}
          </p>
          {extension === "docx" && (
            <label className="flex items-center gap-2 text-sm text-foreground">
              <input type="checkbox" checked={autolink} onChange={(e) => setAutolink(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
              {t.autolink}
            </label>
          )}
          {extension === "pdf" && (
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-sm font-medium text-foreground">{t.pdfLegend}</legend>
              {(["editable", "layout"] as const).map((mode) => {
                const choice = mode === "editable" ? t.pdfEditable : t.pdfLayout;
                return (
                  <label key={mode} className="flex items-start gap-2 text-sm text-foreground">
                    <input type="radio" name="pdf-mode" value={mode} checked={pdfMode === mode} onChange={() => setPdfMode(mode)} className="mt-1 h-4 w-4 accent-[var(--accent)]" />
                    <span>
                      <span className="block">{choice.label}</span>
                      <span className="block text-xs text-muted">{choice.detail}</span>
                    </span>
                  </label>
                );
              })}
            </fieldset>
          )}
        </div>
      )}

      <p className="text-xs text-muted">{t.howRead}</p>
      <div className="flex justify-end">
        <Button type="submit" size="lg" disabled={!ready}>
          {t.submit}
        </Button>
      </div>
    </form>
  );
}
