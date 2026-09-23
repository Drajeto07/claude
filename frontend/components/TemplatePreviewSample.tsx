import type { CSSProperties } from "react";

import type { TemplatePreview } from "@/types/document";

/**
 * A few words of real sample text rendered in the template's own
 * fontFamily/alignment/lineSpacing (from its actual Paragraph rules, via
 * TemplateSummary.preview) -- a genuine visual preview rather than a
 * hand-guessed stand-in that could drift from what applying the template
 * actually produces.
 */
export function TemplatePreviewSample({ preview }: { preview: TemplatePreview }) {
  if (!preview.fontFamily && !preview.alignment && !preview.lineSpacing) return null;

  return (
    <div
      className="mt-2 rounded border border-zinc-200 bg-zinc-50 px-2.5 py-2 text-[11px] text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950/40 dark:text-zinc-400"
      style={{
        fontFamily: preview.fontFamily ?? undefined,
        textAlign: (preview.alignment as CSSProperties["textAlign"]) ?? undefined,
        lineHeight: preview.lineSpacing ?? undefined,
      }}
    >
      Aa &mdash; sample paragraph text in this template&rsquo;s real font, alignment and spacing.
    </div>
  );
}
