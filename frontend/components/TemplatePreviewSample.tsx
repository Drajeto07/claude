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
      // Paper stays white in both themes, like the page in the editor and the dashboard thumbnails.
      className={`paper pointer-events-none mt-2 overflow-hidden rounded-lg border border-line bg-white ${className}`}
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
