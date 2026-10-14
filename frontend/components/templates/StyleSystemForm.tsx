"use client";

import type { ReactNode } from "react";

import { ColorField, NumberField, SelectField, TextField, ToggleField } from "@/components/templates/fields";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import type { Alignment, HeadingLevel, PageSize, StyleSystem, TextBlockKey, TextStyle } from "@/types/document";

// Suggestions only -- any installed font name can be typed.
const FONT_SUGGESTIONS = [
  "Times New Roman",
  "Arial",
  "Calibri",
  "Cambria",
  "Georgia",
  "Garamond",
  "Book Antiqua",
  "Verdana",
  "Tahoma",
  "Segoe UI",
  "Courier New",
  "Consolas",
] as const;

const ALIGNMENTS: Alignment[] = ["left", "center", "right", "justify"];
const PAGE_SIZES: { value: PageSize; label: string }[] = [
  { value: "A4", label: "A4" },
  { value: "Letter", label: "Letter" },
  { value: "Legal", label: "Legal" },
];

function Section({ title, hint, defaultOpen = false, children }: { title: string; hint?: string; defaultOpen?: boolean; children: ReactNode }) {
  return (
    <details open={defaultOpen} className="group rounded-2xl border border-line bg-surface">
      <summary className="cursor-pointer select-none px-4 py-3 text-sm font-semibold text-foreground marker:text-muted">
        {title}
        {hint && <span className="mt-0.5 block text-xs font-normal text-muted">{hint}</span>}
      </summary>
      <div className="border-t border-line px-4 py-4">{children}</div>
    </details>
  );
}

const grid = "grid grid-cols-2 gap-3 sm:grid-cols-3";

function useAlignments() {
  const { m } = useI18n();
  return ALIGNMENTS.map((value) => ({ value, label: m.styleForm.alignments[value] }));
}

function TextStyleFields({ value, onChange }: { value: TextStyle; onChange: (next: TextStyle) => void }) {
  const { m } = useI18n();
  const f = m.styleForm.fields;
  const alignments = useAlignments();
  const set = <K extends keyof TextStyle>(field: K) => (fieldValue: TextStyle[K]) => onChange({ ...value, [field]: fieldValue });
  return (
    <div className={grid}>
      <TextField label={f.font} value={value.fontFamily} onChange={set("fontFamily")} suggestions={FONT_SUGGESTIONS} maxLength={100} />
      <NumberField label={f.size} value={value.fontSizePt} onChange={set("fontSizePt")} min={1} max={400} step={0.5} />
      <ColorField label={f.colour} value={value.color} onChange={set("color")} />
      <SelectField label={f.alignment} value={value.alignment} onChange={set("alignment")} options={alignments} />
      <NumberField label={f.lineSpacing} value={value.lineSpacing} onChange={set("lineSpacing")} min={0.5} max={10} step={0.05} />
      <NumberField label={f.spaceBefore} value={value.spaceBeforePt} onChange={set("spaceBeforePt")} min={0} max={500} step={1} />
      <NumberField label={f.spaceAfter} value={value.spaceAfterPt} onChange={set("spaceAfterPt")} min={0} max={500} step={1} />
      <NumberField label={f.indentLeft} value={value.indentLeftCm} onChange={set("indentLeftCm")} min={-10} max={20} step={0.25} />
      <NumberField label={f.firstLine} value={value.firstLineIndentCm} onChange={set("firstLineIndentCm")} min={-10} max={10} step={0.25} />
      <ToggleField label={f.bold} value={value.bold} onChange={set("bold")} />
      <ToggleField label={f.italic} value={value.italic} onChange={set("italic")} />
      <ToggleField label={f.underline} value={value.underline} onChange={set("underline")} />
    </div>
  );
}

const TEXT_BLOCKS: { key: TextBlockKey; title: "lists" | "tables" | "captions" | "quotes" | "footnotes" | "code"; hint?: "tablesHint" | "captionsHint" | "codeHint" }[] = [
  { key: "lists", title: "lists" },
  { key: "tables", title: "tables", hint: "tablesHint" },
  { key: "captions", title: "captions", hint: "captionsHint" },
  { key: "quotes", title: "quotes" },
  { key: "footnotes", title: "footnotes" },
  { key: "code", title: "code", hint: "codeHint" },
];

/**
 * Edits every part of a StyleSystem (backend formatting/style_system.py). An
 * empty field means "not set", never a value of its own; the server validates
 * everything again on save.
 */
export function StyleSystemForm({ value, onChange }: { value: StyleSystem; onChange: (next: StyleSystem) => void }) {
  const { m } = useI18n();
  const f = m.styleForm.fields;
  const s = m.styleForm.sections;
  const alignments = useAlignments();
  const setPage = <K extends keyof StyleSystem["page"]>(field: K) => (fieldValue: StyleSystem["page"][K]) => onChange({ ...value, page: { ...value.page, [field]: fieldValue } });
  const setBlock = (key: TextBlockKey) => (next: TextStyle) => onChange({ ...value, [key]: next });
  const setHeading = (level: HeadingLevel) => (next: TextStyle) => onChange({ ...value, headings: { ...value.headings, [level]: next } });
  const headingTitle = (level: string) => format(s.heading, { level: level.slice(1) });

  return (
    <div className="flex flex-col gap-3">
      <Section title={s.page} defaultOpen>
        <div className={grid}>
          <SelectField label={f.pageSize} value={value.page.size} onChange={setPage("size")} options={PAGE_SIZES} />
          <SelectField
            label={f.orientation}
            value={value.page.orientation}
            onChange={setPage("orientation")}
            options={[
              { value: "portrait", label: m.styleForm.orientations.portrait },
              { value: "landscape", label: m.styleForm.orientations.landscape },
            ]}
          />
          <span className="hidden sm:block" />
          <NumberField label={f.marginTop} value={value.page.marginTopCm} onChange={setPage("marginTopCm")} min={0} max={10} step={0.25} />
          <NumberField label={f.marginBottom} value={value.page.marginBottomCm} onChange={setPage("marginBottomCm")} min={0} max={10} step={0.25} />
          <NumberField label={f.marginLeft} value={value.page.marginLeftCm} onChange={setPage("marginLeftCm")} min={0} max={10} step={0.25} />
          <NumberField label={f.marginRight} value={value.page.marginRightCm} onChange={setPage("marginRightCm")} min={0} max={10} step={0.25} />
        </div>
      </Section>

      <Section title={s.everywhere} hint={s.everywhereHint} defaultOpen>
        <div className={grid}>
          <TextField
            label={f.font}
            value={value.document.fontFamily}
            onChange={(fontFamily) => onChange({ ...value, document: { ...value.document, fontFamily } })}
            suggestions={FONT_SUGGESTIONS}
            maxLength={100}
          />
          <ColorField label={f.colour} value={value.document.color} onChange={(color) => onChange({ ...value, document: { ...value.document, color } })} />
        </div>
      </Section>

      <Section title={s.body} hint={s.bodyHint} defaultOpen>
        <TextStyleFields value={value.paragraph} onChange={setBlock("paragraph")} />
      </Section>

      <Section title={s.headings} defaultOpen>
        <div className="flex flex-col gap-5">
          {(["h1", "h2", "h3"] as const).map((level) => (
            <div key={level}>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{headingTitle(level)}</h3>
              <TextStyleFields value={value.headings[level]} onChange={setHeading(level)} />
            </div>
          ))}
          <details>
            <summary className="cursor-pointer text-xs font-medium text-accent">{s.moreHeadings}</summary>
            <div className="mt-3 flex flex-col gap-5">
              {(["h4", "h5", "h6"] as const).map((level) => (
                <div key={level}>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{headingTitle(level)}</h3>
                  <TextStyleFields value={value.headings[level]} onChange={setHeading(level)} />
                </div>
              ))}
            </div>
          </details>
        </div>
      </Section>

      {TEXT_BLOCKS.map((block) => (
        <Section key={block.key} title={s[block.title]} hint={block.hint ? s[block.hint] : undefined}>
          <TextStyleFields value={value[block.key]} onChange={setBlock(block.key)} />
        </Section>
      ))}

      <Section title={s.images}>
        <div className={grid}>
          <NumberField
            label={f.imageWidth}
            value={value.images.widthPercent}
            onChange={(widthPercent) => onChange({ ...value, images: { ...value.images, widthPercent } })}
            min={1}
            max={100}
            step={5}
          />
          <SelectField
            label={f.alignment}
            value={value.images.alignment}
            onChange={(alignment) => onChange({ ...value, images: { ...value.images, alignment } })}
            options={alignments.filter((option) => option.value !== "justify") as { value: "left" | "center" | "right"; label: string }[]}
          />
        </div>
      </Section>

      <Section title={s.headerFooter} hint={s.headerFooterHint}>
        <div className={grid}>
          <TextField label={f.headerText} value={value.header.text} onChange={(text) => onChange({ ...value, header: { text } })} maxLength={500} />
          <TextField label={f.footerText} value={value.footer.text} onChange={(text) => onChange({ ...value, footer: { ...value.footer, text } })} maxLength={500} />
          <ToggleField label={f.pageNumbers} value={value.footer.pageNumbers} onChange={(pageNumbers) => onChange({ ...value, footer: { ...value.footer, pageNumbers } })} />
        </div>
      </Section>
    </div>
  );
}
