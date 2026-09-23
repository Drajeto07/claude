"use client";

import { AlignCenter, AlignJustify, AlignLeft, AlignRight, Bold, Italic, Underline as UnderlineIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import { clearElementStyle, setElementStyle } from "@/services/api";
import type { Document, Element, FormattingProperty } from "@/types/document";

const FONT_FAMILIES = ["Arial", "Times New Roman", "Calibri", "Georgia", "Courier New"];

const inputClass =
  "w-full rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100";

function currentCss(document: Document, element: Element): Record<string, string> {
  return element.styleRef ? (document.resolvedStyles[element.styleRef] ?? {}) : {};
}

function imageAlignmentFromCss(css: Record<string, string>): string {
  if (css["margin-left"] === "auto" && css["margin-right"] === "auto") return "center";
  if (css["margin-left"] === "auto") return "right";
  return "left";
}

function Row({ label, onReset, children }: { label: string; onReset: () => void; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="flex items-center justify-between text-xs text-zinc-500 dark:text-zinc-400">
        {label}
        <button type="button" onClick={onReset} title="Reset to template default" className="text-zinc-400 hover:text-accent dark:hover:text-accent">
          reset
        </button>
      </span>
      {children}
    </label>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return <p className="mb-2 text-xs font-semibold tracking-wide text-zinc-400 uppercase dark:text-zinc-500">{children}</p>;
}

function ToggleIconButton({ active, onClick, label, children }: { active: boolean; onClick: () => void; label: string; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={active}
      title={label}
      className={`flex h-8 w-8 items-center justify-center rounded transition-colors ${
        active ? "bg-accent/10 text-accent" : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
      }`}
    >
      {children}
    </button>
  );
}

/**
 * Spec §7.9 tier 1 -- an explicit, per-element user change, the highest
 * formatting priority there is. Wins over any template/instructions
 * automatically (NFR-008), persisted server-side, survives a reformat.
 * Lives in the persistent right sidebar (RightSidebar.tsx) now, grouped
 * into Text/Paragraph sections rather than one flat horizontal row.
 */
export function PropertiesPanel({
  document,
  selectedElementId,
  onUpdated,
  onBeforeMutate,
}: {
  document: Document;
  selectedElementId: string | null;
  onUpdated: (updated: Document) => void;
  /** Flushes a pending autosave before this panel's own mutation, so the
   * two can never race (see useFormattingState.ts's identical concern). */
  onBeforeMutate: () => Promise<unknown>;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const element = document.elements.find((el) => el.id === selectedElementId) ?? null;

  if (!element) {
    return <p className="text-sm text-zinc-500 dark:text-zinc-400">Select an element in the document to edit its style.</p>;
  }

  async function apply(property: FormattingProperty, value: string, unit?: string) {
    setPending(true);
    setError(null);
    try {
      await onBeforeMutate();
      onUpdated(await setElementStyle(document.id, element!.id, { property, value, unit }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update style.");
    } finally {
      setPending(false);
    }
  }

  async function reset(property: FormattingProperty) {
    setPending(true);
    setError(null);
    try {
      await onBeforeMutate();
      onUpdated(await clearElementStyle(document.id, element!.id, property));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset style.");
    } finally {
      setPending(false);
    }
  }

  const css = currentCss(document, element);
  const isImage = element.type === "image";
  // Forces a remount (so defaultValue/defaultChecked re-initialize) exactly
  // when the selected element or its resolved style actually changes --
  // keying on the style content itself (not e.g. a revision counter) is
  // what makes this precise: a revision bump from mutating a *different*
  // element must not be mistaken for this one's style having changed, and
  // vice versa a real change here must never be missed.
  const formKey = `${element.id}:${JSON.stringify(css)}`;

  return (
    <fieldset key={formKey} disabled={pending} className="flex flex-col gap-5 text-sm">
      <p className="text-xs font-semibold tracking-wide text-zinc-400 uppercase dark:text-zinc-500">{element.type}</p>

      {isImage ? (
        <div>
          <SectionLabel>Image</SectionLabel>
          <div className="flex flex-col gap-3">
            <Row label="Width %" onReset={() => reset("imageWidth")}>
              <input
                type="number"
                defaultValue={css["width"]?.replace(/%$/, "") ?? ""}
                onBlur={(e) => e.target.value && apply("imageWidth", e.target.value, "%")}
                className={inputClass}
              />
            </Row>
            <Row label="Alignment" onReset={() => reset("imageAlignment")}>
              <select defaultValue={imageAlignmentFromCss(css)} onChange={(e) => apply("imageAlignment", e.target.value)} className={inputClass}>
                <option value="left">Left</option>
                <option value="center">Center</option>
                <option value="right">Right</option>
              </select>
            </Row>
          </div>
        </div>
      ) : (
        <>
          <div>
            <SectionLabel>Text</SectionLabel>
            <div className="flex flex-col gap-3">
              <div className="grid grid-cols-2 gap-2">
                <Row label="Font family" onReset={() => reset("fontFamily")}>
                  <select defaultValue={css["font-family"] ?? ""} onChange={(e) => e.target.value && apply("fontFamily", e.target.value)} className={inputClass}>
                    <option value="">&ndash;</option>
                    {FONT_FAMILIES.map((font) => (
                      <option key={font} value={font}>
                        {font}
                      </option>
                    ))}
                  </select>
                </Row>
                <Row label="Size (pt)" onReset={() => reset("fontSize")}>
                  <input
                    type="number"
                    defaultValue={css["font-size"]?.replace(/pt$/, "") ?? ""}
                    onBlur={(e) => e.target.value && apply("fontSize", e.target.value, "pt")}
                    className={inputClass}
                  />
                </Row>
              </div>

              <div className="flex items-center gap-1">
                <ToggleIconButton label="Bold" active={css["font-weight"] === "bold"} onClick={() => apply("bold", css["font-weight"] === "bold" ? "false" : "true")}>
                  <Bold className="h-4 w-4" aria-hidden="true" />
                </ToggleIconButton>
                <ToggleIconButton label="Italic" active={css["font-style"] === "italic"} onClick={() => apply("italic", css["font-style"] === "italic" ? "false" : "true")}>
                  <Italic className="h-4 w-4" aria-hidden="true" />
                </ToggleIconButton>
                <ToggleIconButton
                  label="Underline"
                  active={css["text-decoration"] === "underline"}
                  onClick={() => apply("underline", css["text-decoration"] === "underline" ? "false" : "true")}
                >
                  <UnderlineIcon className="h-4 w-4" aria-hidden="true" />
                </ToggleIconButton>
                <span className="mx-1 h-6 w-px bg-zinc-200 dark:bg-zinc-700" aria-hidden="true" />
                <input
                  type="text"
                  title="Text color"
                  aria-label="Text color"
                  placeholder="#000000"
                  defaultValue={css["color"] ?? ""}
                  onBlur={(e) => e.target.value && apply("color", e.target.value)}
                  className="h-8 w-24 rounded border border-zinc-300 bg-white px-2 text-xs text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                />
              </div>

              <div className="flex items-center gap-1">
                <ToggleIconButton label="Align left" active={css["text-align"] === "left"} onClick={() => apply("alignment", "left")}>
                  <AlignLeft className="h-4 w-4" aria-hidden="true" />
                </ToggleIconButton>
                <ToggleIconButton label="Align center" active={css["text-align"] === "center"} onClick={() => apply("alignment", "center")}>
                  <AlignCenter className="h-4 w-4" aria-hidden="true" />
                </ToggleIconButton>
                <ToggleIconButton label="Align right" active={css["text-align"] === "right"} onClick={() => apply("alignment", "right")}>
                  <AlignRight className="h-4 w-4" aria-hidden="true" />
                </ToggleIconButton>
                <ToggleIconButton label="Justify" active={css["text-align"] === "justify"} onClick={() => apply("alignment", "justify")}>
                  <AlignJustify className="h-4 w-4" aria-hidden="true" />
                </ToggleIconButton>
              </div>
            </div>
          </div>

          <div>
            <SectionLabel>Paragraph</SectionLabel>
            <div className="grid grid-cols-2 gap-2">
              <Row label="Line spacing" onReset={() => reset("lineSpacing")}>
                <input type="number" step="0.05" defaultValue={css["line-height"] ?? ""} onBlur={(e) => e.target.value && apply("lineSpacing", e.target.value)} className={inputClass} />
              </Row>
              <Row label="Space after (pt)" onReset={() => reset("paragraphSpacing")}>
                <input
                  type="number"
                  defaultValue={css["margin-bottom"]?.replace(/pt$/, "") ?? ""}
                  onBlur={(e) => e.target.value && apply("paragraphSpacing", e.target.value, "pt")}
                  className={inputClass}
                />
              </Row>
              <Row label="First-line indent (cm)" onReset={() => reset("firstLineIndent")}>
                <input
                  type="number"
                  step="0.25"
                  defaultValue={css["text-indent"]?.replace(/cm$/, "") ?? ""}
                  onBlur={(e) => e.target.value && apply("firstLineIndent", e.target.value, "cm")}
                  className={inputClass}
                />
              </Row>
            </div>
          </div>
        </>
      )}

      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
    </fieldset>
  );
}
