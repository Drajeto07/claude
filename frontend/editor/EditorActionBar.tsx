"use client";

import { Send, Wand2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { JobProgressBar } from "@/components/JobProgressBar";
import { AddElementMenu, type InsertableType } from "@/editor/AddElementMenu";
import type { FormattingState } from "@/editor/useFormatting";

/**
 * The bar under the pages: a one-line AI instruction (applied like the
 * Instructions panel's, with the template kept), the style check, adding an
 * element, and saving now.
 */
export function EditorActionBar({
  formatting,
  onAnalyzeStyle,
  onAddElement,
  onSaveNow,
}: {
  formatting: FormattingState;
  onAnalyzeStyle: () => void;
  onAddElement: (type: InsertableType) => void;
  onSaveNow: () => void;
}) {
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

  const secondaryButton =
    "rounded-full border border-zinc-200 px-3 py-1.5 text-xs font-medium text-zinc-600 hover:border-zinc-300 dark:border-zinc-800 dark:text-zinc-400 dark:hover:border-zinc-700";

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-zinc-200 bg-white px-4 py-2 dark:border-zinc-800 dark:bg-zinc-950 sm:px-6">
      <form onSubmit={submit} className="flex min-w-[16rem] flex-1 items-center gap-2">
        <Wand2 className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
        <input
          value={quickInput}
          onChange={(e) => setQuickInput(e.target.value)}
          placeholder='e.g. "Add a page after the intro"'
          aria-label="AI assistant instruction"
          className="w-full max-w-md rounded-full border border-zinc-300 bg-zinc-50 px-3 py-1.5 text-sm text-zinc-900 focus:border-accent focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        />
        <button
          type="submit"
          disabled={formatting.isApplying || !quickInput.trim()}
          aria-label="Send"
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
        <span className="hidden text-xs text-zinc-400 sm:inline">AI помощник</span>
      )}
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <button type="button" onClick={onAnalyzeStyle} className={secondaryButton}>
          Провери стила
        </button>
        <button type="button" onClick={onAnalyzeStyle} className={secondaryButton}>
          Анализирай текста
        </button>
        <AddElementMenu onAdd={onAddElement} />
        <button
          type="button"
          onClick={onSaveNow}
          className="rounded-full bg-accent px-4 py-1.5 text-xs font-medium text-accent-foreground transition-opacity hover:opacity-90"
        >
          Приложи промени
        </button>
      </div>
    </div>
  );
}
