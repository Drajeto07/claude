"use client";

import { TemplatePreviewSample } from "@/components/TemplatePreviewSample";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages/en";
import type { ReferenceStyle, TextStyle } from "@/types/document";

type Words = Messages["reference"];

/** The reference's tables and lists in words (FMT-001): what applying its look sets on them. */
function structureText(structure: ReferenceStyle["styleSystem"]["structure"], t: Words): string {
  const parts = [
    structure.tables.border && structure.tables.border !== "none" ? format(t.tables, { border: structure.tables.border }) : null,
    structure.tables.headerShading ? format(t.headerShading, { color: structure.tables.headerShading }) : null,
    structure.tables.headerBold ? t.headerBold : null,
    structure.lists.bulletLevels?.length ? format(t.bullets, { marks: structure.lists.bulletLevels.slice(0, 2).map((level) => level.text ?? "•").join(" ") }) : null,
    structure.lists.numberedLevels?.length ? format(t.numbering, { marks: structure.lists.numberedLevels.slice(0, 2).map((level) => level.text ?? level.format).join(" ") }) : null,
    structure.headingNumbering ? t.numberedHeadings : null,
  ];
  return parts.filter(Boolean).join(", ");
}

function describe(style: TextStyle, t: Words): string {
  const alignment: Record<string, string> = t.alignment;
  const parts = [
    style.fontFamily,
    style.fontSizePt ? format(t.pt, { size: style.fontSizePt }) : null,
    style.bold ? t.bold : null,
    style.italic ? t.italic : null,
    style.alignment && style.alignment !== "left" ? alignment[style.alignment] : null,
    style.lineSpacing ? format(t.lineSpacing, { value: style.lineSpacing }) : null,
  ];
  return parts.filter(Boolean).join(", ") || t.notSet;
}

/**
 * What Format by Example read from a reference document, before it's applied:
 * the main styles in words, a sample page in that look (the engine's own
 * resolved styles), and everything that couldn't be taken over.
 */
export function ReferenceStyleSummary({ reference }: { reference: ReferenceStyle }) {
  const { m } = useI18n();
  const t = m.reference;
  const { styleSystem: style } = reference;
  const levels = Object.keys(reference.headingCounts).length;
  const page = style.page;
  const margins = [page.marginTopCm, page.marginRightCm, page.marginBottomCm, page.marginLeftCm];
  const counts = reference.counts;
  const readFrom = (["paragraphs", "lists", "tables", "images"] as const)
    .filter((key) => Number(counts[key]) > 0)
    .map((key) => format(t.counts[key], { count: counts[key] }))
    .join(", ");
  const structure = structureText(style.structure, t);
  const pageText = [
    page.size || page.orientation ? [page.size, page.orientation].filter(Boolean).join(" ") : t.notSet,
    margins.every((margin) => margin !== null && margin !== undefined) ? format(t.margins, { values: margins.join(" / ") }) : null,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-line bg-surface p-3 text-sm">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted">{t.labels.body}</dt>
        <dd className="text-foreground">{describe(style.paragraph, t)}</dd>
        {structure && (
          <>
            <dt className="text-muted">{t.labels.structure}</dt>
            <dd className="text-foreground">{structure}</dd>
          </>
        )}
        <dt className="text-muted">{t.labels.headings}</dt>
        <dd className="text-foreground">
          {levels === 0 ? t.noHeadings : format(t.headingsLine, { levels, from: t.headingsFrom[reference.headingsFrom], style: describe(style.headings.h1, t) })}
        </dd>
        <dt className="text-muted">{t.labels.page}</dt>
        <dd className="text-foreground">{pageText}</dd>
        {style.footer.text && (
          <>
            <dt className="text-muted">{t.labels.footer}</dt>
            <dd className="text-foreground">{style.footer.text}</dd>
          </>
        )}
      </dl>
      {readFrom && <p className="text-xs text-muted">{format(t.readFrom, { items: readFrom })}</p>}
      <TemplatePreviewSample styles={reference.previewStyles} className="h-28" />
      {reference.notes.length > 0 && (
        <ul className="list-disc pl-5 text-xs text-warning">
          {reference.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
