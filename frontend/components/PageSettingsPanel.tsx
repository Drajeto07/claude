"use client";

import { useState } from "react";

import { clearPageSetting, setPageSetting } from "@/services/api";
import type { Document, FormattingProperty } from "@/types/document";

const PAGE_SIZES = ["A4", "Letter", "Legal"];

const inputClass =
  "w-full rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100";
const labelClass = "flex flex-col gap-1 text-xs text-zinc-500 dark:text-zinc-400";

/**
 * The "Настройки" rail panel -- page-level settings (size/orientation/
 * margins/header/footer/page numbers), via the same priority-1
 * live-override mechanism PropertiesPanel uses for per-element styles
 * (backend: set_document_setting/clear_document_setting, targeting the
 * "Document" pseudo-target instead of one element's id) -- wins over
 * template/instructions and survives a reformat, same as any other
 * manual override.
 */
export function PageSettingsPanel({
  document,
  onUpdated,
  onBeforeMutate,
}: {
  document: Document;
  onUpdated: (updated: Document) => void;
  onBeforeMutate: () => Promise<unknown>;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { settings } = document;

  async function apply(property: FormattingProperty, value: string, unit?: string) {
    setPending(true);
    setError(null);
    try {
      await onBeforeMutate();
      onUpdated(await setPageSetting(document.id, { property, value, unit }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update setting.");
    } finally {
      setPending(false);
    }
  }

  async function reset(property: FormattingProperty) {
    setPending(true);
    setError(null);
    try {
      await onBeforeMutate();
      onUpdated(await clearPageSetting(document.id, property));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset setting.");
    } finally {
      setPending(false);
    }
  }

  const formKey = `${document.id}:${JSON.stringify(settings)}`;

  return (
    <fieldset key={formKey} disabled={pending} className="flex flex-col gap-4 text-sm">
      <div>
        <p className="mb-2 text-xs font-semibold tracking-wide text-zinc-400 uppercase dark:text-zinc-500">Page</p>
        <div className="grid grid-cols-2 gap-2">
          <label className={labelClass}>
            Size
            <select defaultValue={settings.pageSize} onChange={(e) => apply("pageSize", e.target.value)} className={inputClass}>
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
          <label className={labelClass}>
            Orientation
            <select defaultValue={settings.orientation} onChange={(e) => apply("orientation", e.target.value)} className={inputClass}>
              <option value="portrait">Portrait</option>
              <option value="landscape">Landscape</option>
            </select>
          </label>
        </div>
      </div>

      <div>
        <p className="mb-2 text-xs font-semibold tracking-wide text-zinc-400 uppercase dark:text-zinc-500">Margins (cm)</p>
        <div className="grid grid-cols-2 gap-2">
          <label className={labelClass}>
            Top
            <input
              type="number"
              step="0.5"
              defaultValue={settings.marginTopCm}
              onBlur={(e) => e.target.value && apply("marginTop", e.target.value, "cm")}
              className={inputClass}
            />
          </label>
          <label className={labelClass}>
            Bottom
            <input
              type="number"
              step="0.5"
              defaultValue={settings.marginBottomCm}
              onBlur={(e) => e.target.value && apply("marginBottom", e.target.value, "cm")}
              className={inputClass}
            />
          </label>
          <label className={labelClass}>
            Left
            <input
              type="number"
              step="0.5"
              defaultValue={settings.marginLeftCm}
              onBlur={(e) => e.target.value && apply("marginLeft", e.target.value, "cm")}
              className={inputClass}
            />
          </label>
          <label className={labelClass}>
            Right
            <input
              type="number"
              step="0.5"
              defaultValue={settings.marginRightCm}
              onBlur={(e) => e.target.value && apply("marginRight", e.target.value, "cm")}
              className={inputClass}
            />
          </label>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-xs font-semibold tracking-wide text-zinc-400 uppercase dark:text-zinc-500">Header &amp; footer</p>
        <label className={labelClass}>
          Header text
          <input
            type="text"
            defaultValue={settings.header ?? ""}
            onBlur={(e) => (e.target.value ? apply("header", e.target.value) : reset("header"))}
            className={inputClass}
          />
        </label>
        <label className={labelClass}>
          Footer text
          <input
            type="text"
            defaultValue={settings.footer ?? ""}
            onBlur={(e) => (e.target.value ? apply("footer", e.target.value) : reset("footer"))}
            className={inputClass}
          />
        </label>
        <label className="flex items-center justify-between text-sm text-zinc-700 dark:text-zinc-300">
          Page numbers
          <input
            type="checkbox"
            defaultChecked={settings.showPageNumbers}
            onChange={(e) => apply("showPageNumbers", e.target.checked ? "true" : "false")}
            className="h-4 w-8 accent-accent"
          />
        </label>
      </div>

      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
    </fieldset>
  );
}
