"use client";

import type { ReactNode } from "react";

import { ColorField, NumberField, SelectField, TextField, ToggleField } from "@/components/templates/fields";
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

const ALIGNMENTS: { value: Alignment; label: string }[] = [
  { value: "left", label: "Left" },
  { value: "center", label: "Center" },
  { value: "right", label: "Right" },
  { value: "justify", label: "Justify" },
];

const PAGE_SIZES: { value: PageSize; label: string }[] = [
  { value: "A4", label: "A4" },
  { value: "Letter", label: "Letter" },
  { value: "Legal", label: "Legal" },
];

function Section({ title, hint, defaultOpen = false, children }: { title: string; hint?: string; defaultOpen?: boolean; children: ReactNode }) {
  return (
    <details open={defaultOpen} className="group rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <summary className="cursor-pointer select-none px-4 py-3 text-sm font-semibold text-zinc-900 marker:text-zinc-400 dark:text-zinc-50">
        {title}
        {hint && <span className="mt-0.5 block text-xs font-normal text-zinc-500 dark:text-zinc-400">{hint}</span>}
      </summary>
      <div className="border-t border-zinc-100 px-4 py-4 dark:border-zinc-800">{children}</div>
    </details>
  );
}

const grid = "grid grid-cols-2 gap-3 sm:grid-cols-3";

function TextStyleFields({ value, onChange }: { value: TextStyle; onChange: (next: TextStyle) => void }) {
  const set = <K extends keyof TextStyle>(field: K) => (fieldValue: TextStyle[K]) => onChange({ ...value, [field]: fieldValue });
  return (
    <div className={grid}>
      <TextField label="Font" value={value.fontFamily} onChange={set("fontFamily")} suggestions={FONT_SUGGESTIONS} maxLength={100} />
      <NumberField label="Size (pt)" value={value.fontSizePt} onChange={set("fontSizePt")} min={1} max={400} step={0.5} />
      <ColorField label="Colour" value={value.color} onChange={set("color")} />
      <SelectField label="Alignment" value={value.alignment} onChange={set("alignment")} options={ALIGNMENTS} />
      <NumberField label="Line spacing" value={value.lineSpacing} onChange={set("lineSpacing")} min={0.5} max={10} step={0.05} />
      <NumberField label="Space after (pt)" value={value.spaceAfterPt} onChange={set("spaceAfterPt")} min={0} max={500} step={1} />
      <NumberField label="First-line indent (cm)" value={value.firstLineIndentCm} onChange={set("firstLineIndentCm")} min={-10} max={10} step={0.25} />
      <ToggleField label="Bold" value={value.bold} onChange={set("bold")} />
      <ToggleField label="Italic" value={value.italic} onChange={set("italic")} />
      <ToggleField label="Underline" value={value.underline} onChange={set("underline")} />
    </div>
  );
}

const TEXT_BLOCKS: { key: TextBlockKey; title: string; hint?: string }[] = [
  { key: "lists", title: "Lists" },
  { key: "tables", title: "Tables", hint: "Text inside table cells." },
  { key: "captions", title: "Captions", hint: "Figure and table captions." },
  { key: "quotes", title: "Quotes" },
  { key: "footnotes", title: "Footnotes" },
  { key: "code", title: "Code blocks", hint: "Keeps its own (monospace) font even when a document-wide font is set." },
];

/**
 * Edits every part of a StyleSystem (backend formatting/style_system.py). An
 * empty field means "not set", never a value of its own; the server validates
 * everything again on save.
 */
export function StyleSystemForm({ value, onChange }: { value: StyleSystem; onChange: (next: StyleSystem) => void }) {
  const setPage = <K extends keyof StyleSystem["page"]>(field: K) => (fieldValue: StyleSystem["page"][K]) =>
    onChange({ ...value, page: { ...value.page, [field]: fieldValue } });
  const setBlock = (key: TextBlockKey) => (next: TextStyle) => onChange({ ...value, [key]: next });
  const setHeading = (level: HeadingLevel) => (next: TextStyle) => onChange({ ...value, headings: { ...value.headings, [level]: next } });

  return (
    <div className="flex flex-col gap-3">
      <Section title="Page" defaultOpen>
        <div className={grid}>
          <SelectField label="Size" value={value.page.size} onChange={setPage("size")} options={PAGE_SIZES} />
          <SelectField
            label="Orientation"
            value={value.page.orientation}
            onChange={setPage("orientation")}
            options={[
              { value: "portrait", label: "Portrait" },
              { value: "landscape", label: "Landscape" },
            ]}
          />
          <span className="hidden sm:block" />
          <NumberField label="Top margin (cm)" value={value.page.marginTopCm} onChange={setPage("marginTopCm")} min={0} max={10} step={0.25} />
          <NumberField label="Bottom margin (cm)" value={value.page.marginBottomCm} onChange={setPage("marginBottomCm")} min={0} max={10} step={0.25} />
          <NumberField label="Left margin (cm)" value={value.page.marginLeftCm} onChange={setPage("marginLeftCm")} min={0} max={10} step={0.25} />
          <NumberField label="Right margin (cm)" value={value.page.marginRightCm} onChange={setPage("marginRightCm")} min={0} max={10} step={0.25} />
        </div>
      </Section>

      <Section title="Text everywhere" hint="Font and colour for all text that doesn't set its own." defaultOpen>
        <div className={grid}>
          <TextField
            label="Font"
            value={value.document.fontFamily}
            onChange={(fontFamily) => onChange({ ...value, document: { ...value.document, fontFamily } })}
            suggestions={FONT_SUGGESTIONS}
            maxLength={100}
          />
          <ColorField label="Colour" value={value.document.color} onChange={(color) => onChange({ ...value, document: { ...value.document, color } })} />
        </div>
      </Section>

      <Section title="Body text" hint="Ordinary paragraphs." defaultOpen>
        <TextStyleFields value={value.paragraph} onChange={setBlock("paragraph")} />
      </Section>

      <Section title="Headings" defaultOpen>
        <div className="flex flex-col gap-5">
          {(["h1", "h2", "h3"] as const).map((level) => (
            <div key={level}>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Heading {level.slice(1)}</h3>
              <TextStyleFields value={value.headings[level]} onChange={setHeading(level)} />
            </div>
          ))}
          <details>
            <summary className="cursor-pointer text-xs font-medium text-accent">Headings 4–6</summary>
            <div className="mt-3 flex flex-col gap-5">
              {(["h4", "h5", "h6"] as const).map((level) => (
                <div key={level}>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Heading {level.slice(1)}</h3>
                  <TextStyleFields value={value.headings[level]} onChange={setHeading(level)} />
                </div>
              ))}
            </div>
          </details>
        </div>
      </Section>

      {TEXT_BLOCKS.map((block) => (
        <Section key={block.key} title={block.title} hint={block.hint}>
          <TextStyleFields value={value[block.key]} onChange={setBlock(block.key)} />
        </Section>
      ))}

      <Section title="Images">
        <div className={grid}>
          <NumberField
            label="Width (% of the line)"
            value={value.images.widthPercent}
            onChange={(widthPercent) => onChange({ ...value, images: { ...value.images, widthPercent } })}
            min={1}
            max={100}
            step={5}
          />
          <SelectField
            label="Alignment"
            value={value.images.alignment}
            onChange={(alignment) => onChange({ ...value, images: { ...value.images, alignment } })}
            options={ALIGNMENTS.filter((option) => option.value !== "justify") as { value: "left" | "center" | "right"; label: string }[]}
          />
        </div>
      </Section>

      <Section title="Header and footer">
        <div className={grid}>
          <TextField label="Header text" value={value.header.text} onChange={(text) => onChange({ ...value, header: { text } })} maxLength={500} />
          <TextField
            label="Footer text"
            value={value.footer.text}
            onChange={(text) => onChange({ ...value, footer: { ...value.footer, text } })}
            maxLength={500}
          />
          <ToggleField
            label="Page numbers"
            value={value.footer.pageNumbers}
            onChange={(pageNumbers) => onChange({ ...value, footer: { ...value.footer, pageNumbers } })}
          />
        </div>
      </Section>
    </div>
  );
}
