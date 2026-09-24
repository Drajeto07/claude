import { cssToStyle } from "@/editor/cssStyle";
import type { ResolvedStyles } from "@/types/document";

/**
 * A miniature page of sample text in a template's real look: the resolved
 * styles come from the backend engine (Template.previewStyles), and the page
 * uses the editor's own base CSS (.ProseMirror), so what the card shows is
 * what applying the template produces. Bulgarian sample text on purpose: it
 * shows whether the chosen font actually has Cyrillic.
 */
export function TemplatePreviewSample({ styles, className = "h-28" }: { styles: ResolvedStyles; className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none mt-2 overflow-hidden rounded border border-zinc-200 bg-white text-zinc-900 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-50 ${className}`}
    >
      <div className="ProseMirror" style={{ zoom: 0.42, padding: "28px 40px" }}>
        <h1 style={cssToStyle(styles["Heading 1"])}>Заглавие на документа</h1>
        <p style={cssToStyle(styles["Paragraph"])}>
          Примерен абзац с текст, оформен според шаблона: шрифт, размер, подравняване и междуредие.
          Втори ред, за да се вижда разстоянието между редовете.
        </p>
        <h2 style={cssToStyle(styles["Heading 2"])}>Подзаглавие</h2>
        <p style={cssToStyle(styles["Paragraph"])}>Още текст под подзаглавието.</p>
      </div>
    </div>
  );
}
