"use client";

import { useState, type ReactNode } from "react";

import { clearElementStyle, setElementStyle } from "@/services/api";
import type { Document, Element, FormattingProperty } from "@/types/document";

const FONT_FAMILIES = ["Arial", "Times New Roman", "Calibri", "Georgia", "Courier New"];

const inputClass =
  "w-full rounded border border-zinc-300 bg-white px-2 py-1 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100";

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
        <button
          type="button"
          onClick={onReset}
          title="Reset to template default"
          className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
        >
          reset
        </button>
      </span>
      {children}
    </label>
  );
}

/**
 * Spec §7.9 tier 1 -- an explicit, per-element user change, the highest
 * formatting priority there is. Wins over any template/instructions
 * automatically (NFR-008), persisted server-side, survives a reformat.
 */
export function PropertiesPanel({
  document,
  selectedElementId,
  onUpdated,
}: {
  document: Document;
  selectedElementId: string | null;
  onUpdated: (updated: Document) => void;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const element = document.elements.find((el) => el.id === selectedElementId) ?? null;

  if (!element) {
    return (
      <div className="rounded-lg border border-zinc-200 bg-white p-3 text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
        Click an element in the document to edit its style.
      </div>
    );
  }

  async function apply(property: FormattingProperty, value: string, unit?: string) {
    setPending(true);
    setError(null);
    try {
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
    <div className="sticky top-6 rounded-lg border border-zinc-200 bg-white p-3 text-sm dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="mb-3 text-xs font-semibold tracking-wide text-zinc-500 uppercase dark:text-zinc-400">
        Properties &mdash; {element.type}
      </h2>
      <fieldset key={formKey} disabled={pending} className="flex flex-col gap-3">
        {isImage ? (
          <>
            <Row label="Width %" onReset={() => reset("imageWidth")}>
              <input
                type="number"
                defaultValue={css["width"]?.replace(/%$/, "") ?? ""}
                onBlur={(e) => e.target.value && apply("imageWidth", e.target.value, "%")}
                className={inputClass}
              />
            </Row>
            <Row label="Alignment" onReset={() => reset("imageAlignment")}>
              <select
                defaultValue={imageAlignmentFromCss(css)}
                onChange={(e) => apply("imageAlignment", e.target.value)}
                className={inputClass}
              >
                <option value="left">Left</option>
                <option value="center">Center</option>
                <option value="right">Right</option>
              </select>
            </Row>
          </>
        ) : (
          <>
            <Row label="Font family" onReset={() => reset("fontFamily")}>
              <select
                defaultValue={css["font-family"] ?? ""}
                onChange={(e) => e.target.value && apply("fontFamily", e.target.value)}
                className={inputClass}
              >
                <option value="">&ndash;</option>
                {FONT_FAMILIES.map((font) => (
                  <option key={font} value={font}>
                    {font}
                  </option>
                ))}
              </select>
            </Row>
            <Row label="Font size (pt)" onReset={() => reset("fontSize")}>
              <input
                type="number"
                defaultValue={css["font-size"]?.replace(/pt$/, "") ?? ""}
                onBlur={(e) => e.target.value && apply("fontSize", e.target.value, "pt")}
                className={inputClass}
              />
            </Row>
            <Row label="Color" onReset={() => reset("color")}>
              <input
                type="text"
                placeholder="e.g. #cc0000 or red"
                defaultValue={css["color"] ?? ""}
                onBlur={(e) => e.target.value && apply("color", e.target.value)}
                className={inputClass}
              />
            </Row>
            <Row label="Bold" onReset={() => reset("bold")}>
              <input
                type="checkbox"
                defaultChecked={css["font-weight"] === "bold"}
                onChange={(e) => apply("bold", e.target.checked ? "true" : "false")}
              />
            </Row>
            <Row label="Italic" onReset={() => reset("italic")}>
              <input
                type="checkbox"
                defaultChecked={css["font-style"] === "italic"}
                onChange={(e) => apply("italic", e.target.checked ? "true" : "false")}
              />
            </Row>
            <Row label="Underline" onReset={() => reset("underline")}>
              <input
                type="checkbox"
                defaultChecked={css["text-decoration"] === "underline"}
                onChange={(e) => apply("underline", e.target.checked ? "true" : "false")}
              />
            </Row>
            <Row label="Alignment" onReset={() => reset("alignment")}>
              <select
                defaultValue={css["text-align"] ?? ""}
                onChange={(e) => e.target.value && apply("alignment", e.target.value)}
                className={inputClass}
              >
                <option value="">&ndash;</option>
                <option value="left">Left</option>
                <option value="center">Center</option>
                <option value="right">Right</option>
                <option value="justify">Justify</option>
              </select>
            </Row>
            <Row label="Line spacing" onReset={() => reset("lineSpacing")}>
              <input
                type="number"
                step="0.05"
                defaultValue={css["line-height"] ?? ""}
                onBlur={(e) => e.target.value && apply("lineSpacing", e.target.value)}
                className={inputClass}
              />
            </Row>
            <Row label="Paragraph spacing (pt)" onReset={() => reset("paragraphSpacing")}>
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
          </>
        )}
      </fieldset>
      {error && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{error}</p>}
    </div>
  );
}
