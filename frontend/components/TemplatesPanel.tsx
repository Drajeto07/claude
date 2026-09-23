"use client";

import { CheckCircle2 } from "lucide-react";

import { TemplatePreviewSample } from "@/components/TemplatePreviewSample";
import type { FormattingState } from "@/editor/useFormattingState";

/**
 * The "Шаблони" rail panel -- template selection only. Shares its
 * templateId/instructionsText state with InstructionsPanel via the
 * useFormattingState hook (called once in DocumentEditor) so applying a
 * template here never silently drops instructions typed in the other
 * panel, and vice versa (see useFormattingState.ts's own doc comment).
 */
export function TemplatesPanel({ state }: { state: FormattingState }) {
  const { templates, templateId, setTemplateId, isApplying, error, notice, handleApply } = state;

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        Choose a built-in template. Applying it keeps any instructions already entered in the Instructions panel.
      </p>
      <div className="flex flex-col gap-2">
        <button
          type="button"
          onClick={() => setTemplateId("")}
          className={`flex items-center justify-between rounded-lg border px-3 py-2.5 text-left text-sm transition-colors ${
            templateId === ""
              ? "border-accent bg-accent/5 text-zinc-900 dark:text-zinc-50"
              : "border-zinc-200 text-zinc-600 hover:border-zinc-300 dark:border-zinc-800 dark:text-zinc-400"
          }`}
        >
          No template
          {templateId === "" && <CheckCircle2 className="h-4 w-4 text-accent" aria-hidden="true" />}
        </button>
        {templates.map((template) => (
          <button
            key={template.id}
            type="button"
            onClick={() => setTemplateId(template.id)}
            className={`rounded-lg border px-3 py-2.5 text-left text-sm transition-colors ${
              templateId === template.id
                ? "border-accent bg-accent/5 text-zinc-900 dark:text-zinc-50"
                : "border-zinc-200 text-zinc-600 hover:border-zinc-300 dark:border-zinc-800 dark:text-zinc-400"
            }`}
          >
            <span className="flex items-center justify-between">
              <span>
                <span className="block font-medium">{template.name}</span>
                {template.description && <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">{template.description}</span>}
              </span>
              {templateId === template.id && <CheckCircle2 className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />}
            </span>
            <TemplatePreviewSample preview={template.preview} />
          </button>
        ))}
      </div>
      <button
        type="button"
        onClick={() => handleApply()}
        disabled={isApplying}
        className="rounded-full bg-accent px-6 py-2.5 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isApplying ? "Applying..." : "Apply formatting"}
      </button>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {notice && (
        <p className={`text-sm ${notice.kind === "success" ? "text-green-700 dark:text-green-400" : "text-amber-700 dark:text-amber-400"}`}>
          {notice.text}
        </p>
      )}
    </div>
  );
}
