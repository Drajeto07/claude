import { TemplatePreviewSample } from "@/components/TemplatePreviewSample";
import type { ReferenceStyle, TextStyle } from "@/types/document";

const HEADINGS_FROM: Record<ReferenceStyle["headingsFrom"], string> = {
  styles: "from its Word heading styles",
  look: "recognised by their look",
  ai: "picked out by the AI",
  none: "",
};

const ALIGNMENT: Record<string, string> = { center: "centred", right: "right-aligned", justify: "justified" };

function describe(style: TextStyle): string {
  const parts = [
    style.fontFamily,
    style.fontSizePt ? `${style.fontSizePt} pt` : null,
    style.bold ? "bold" : null,
    style.italic ? "italic" : null,
    style.alignment ? ALIGNMENT[style.alignment] : null,
    style.lineSpacing ? `line spacing ${style.lineSpacing}` : null,
  ];
  return parts.filter(Boolean).join(", ") || "not set";
}

/**
 * What Format by Example read from a reference document, before it's applied:
 * the main styles in words, a sample page in that look (the engine's own
 * resolved styles), and everything that couldn't be taken over.
 */
export function ReferenceStyleSummary({ reference }: { reference: ReferenceStyle }) {
  const { styleSystem: style } = reference;
  const levels = Object.keys(reference.headingCounts).length;
  const page = style.page;
  const margins = [page.marginTopCm, page.marginRightCm, page.marginBottomCm, page.marginLeftCm];
  const counts = reference.counts;
  const readFrom = [
    [counts.paragraphs, "paragraph"],
    [counts.lists, "list"],
    [counts.tables, "table"],
    [counts.images, "picture"],
  ]
    .filter(([count]) => Number(count) > 0)
    .map(([count, noun]) => `${count} ${noun}${count === 1 ? "" : "s"}`)
    .join(", ");

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-zinc-200 bg-white p-3 text-sm dark:border-zinc-800 dark:bg-zinc-900">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-zinc-500 dark:text-zinc-400">Body text</dt>
        <dd className="text-zinc-900 dark:text-zinc-100">{describe(style.paragraph)}</dd>
        <dt className="text-zinc-500 dark:text-zinc-400">Headings</dt>
        <dd className="text-zinc-900 dark:text-zinc-100">
          {levels === 0 ? (
            "none found"
          ) : (
            <>
              {levels} level{levels === 1 ? "" : "s"}, {HEADINGS_FROM[reference.headingsFrom]}. Heading 1: {describe(style.headings.h1)}
            </>
          )}
        </dd>
        <dt className="text-zinc-500 dark:text-zinc-400">Page</dt>
        <dd className="text-zinc-900 dark:text-zinc-100">
          {page.size || page.orientation ? [page.size, page.orientation].filter(Boolean).join(" ") : "not set"}
          {margins.every((margin) => margin !== null && margin !== undefined) && `, margins ${margins.join(" / ")} cm`}
        </dd>
        {style.footer.text && (
          <>
            <dt className="text-zinc-500 dark:text-zinc-400">Footer</dt>
            <dd className="text-zinc-900 dark:text-zinc-100">{style.footer.text}</dd>
          </>
        )}
      </dl>
      {readFrom && <p className="text-xs text-zinc-500 dark:text-zinc-400">Read from {readFrom}.</p>}
      <TemplatePreviewSample styles={reference.previewStyles} className="h-28" />
      {reference.notes.length > 0 && (
        <ul className="list-disc pl-5 text-xs text-amber-700 dark:text-amber-400">
          {reference.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
