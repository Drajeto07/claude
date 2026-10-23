"use client";

import { Send, Wand2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { JobProgressBar } from "@/components/JobProgressBar";
import { AddElementMenu, type InsertableType } from "@/editor/AddElementMenu";
import type { FormattingState } from "@/editor/useFormatting";
import { useI18n } from "@/i18n/I18nProvider";

/**
 * The bar under the pages: a one-line AI instruction (applied like the
 * Instructions panel's, with the template kept), the style check, adding an
 * element, and saving now.
 */
export function EditorActionBar({
  formatting,
  onAnalyzeStyle,
  onAddElement,
  onAddImage,
  onSaveNow,
}: {
  formatting: FormattingState;
  onAnalyzeStyle: () => void;
  onAddElement: (type: InsertableType) => void;
  onAddImage?: (files: File[]) => void;
  onSaveNow: () => void;
}) {
  const { m } = useI18n();
  const t = m.edBars;
  const [quickInput, setQuickInput] = useState("");

  function submit(e: FormEvent) {
    e.preventDefault();
    const instructions = quickInput.trim();
    if (!instructions) return;
    formatting.setInstructionsText(instructions);
    setQuickInput("");
    // Passed along too: the state set just above only arrives with the next render.
    void formatting.handleApply("quick", { instructionsText: instructions });
  }

  const secondaryButton = "rounded-full border border-line px-3 py-1.5 text-xs font-medium text-foreground hover:border-line-strong hover:bg-surface-muted";

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-line bg-surface px-4 py-2 sm:px-6">
      <form onSubmit={submit} className="flex min-w-[16rem] flex-1 items-center gap-2">
        <Wand2 className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
        <input
          value={quickInput}
          onChange={(e) => setQuickInput(e.target.value)}
          placeholder={t.aiPlaceholder}
          aria-label={t.aiLabel}
          className="w-full max-w-md rounded-full border border-line bg-surface-muted px-3 py-1.5 text-sm text-foreground placeholder:text-muted focus:border-accent focus:outline-none"
        />
        <button
          type="submit"
          disabled={formatting.isApplying || !quickInput.trim()}
          aria-label={t.send}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Send className="h-4 w-4" aria-hidden="true" />
        </button>
      </form>
      {formatting.applyingFrom === "quick" && formatting.progress ? (
        <div className="w-44 shrink-0">
          <JobProgressBar progress={formatting.progress} />
        </div>
      ) : (
        <span className="hidden text-xs text-muted sm:inline">{t.aiAssistant}</span>
      )}
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <button type="button" onClick={onAnalyzeStyle} className={secondaryButton}>
          {t.checkStyle}
        </button>
        <AddElementMenu onAdd={onAddElement} onAddImage={onAddImage} />
        <button type="button" onClick={onSaveNow} className="rounded-full bg-accent px-4 py-1.5 text-xs font-medium text-accent-foreground transition-opacity hover:opacity-90">
          {t.saveNow}
        </button>
      </div>
    </div>
  );
}
