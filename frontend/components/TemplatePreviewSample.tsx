import { cssToStyle } from "@/editor/cssStyle";
import { useI18n } from "@/i18n/I18nProvider";
import type { ResolvedStyles } from "@/types/document";

/**
 * A miniature page of sample text in a template's real look: the resolved
 * styles come from the backend engine (Template.previewStyles), and the page
 * uses the editor's own base CSS (.ProseMirror), so what the card shows is
 * what applying the template produces. The sample text is in the interface's
 * language (S2-098); in Bulgarian it still shows whether the chosen font has
 * Cyrillic (e2e/templates.spec.ts checks it is drawn in the template's font).
 */
export function TemplatePreviewSample({ styles, className = "h-28" }: { styles: ResolvedStyles; className?: string }) {
  const t = useI18n().m.templateSamples.card;
  return (
    <div
      aria-hidden="true"
      // Paper stays white in both themes, like the page in the editor and the dashboard thumbnails.
      className={`paper pointer-events-none mt-2 overflow-hidden rounded-lg border border-line bg-white ${className}`}
    >
      <div className="ProseMirror" style={{ zoom: 0.42, padding: "28px 40px" }}>
        <h1 style={cssToStyle(styles["Heading 1"])}>{t.heading}</h1>
        <p style={cssToStyle(styles["Paragraph"])}>{t.paragraph}</p>
        <h2 style={cssToStyle(styles["Heading 2"])}>{t.subheading}</h2>
        <p style={cssToStyle(styles["Paragraph"])}>{t.more}</p>
      </div>
    </div>
  );
}
