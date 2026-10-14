"use client";

import { useState } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { useI18n } from "@/i18n/I18nProvider";
import { clearPageSetting, errorMessage, setPageSetting } from "@/services/api";
import type { Document, FormattingProperty } from "@/types/document";

const PAGE_SIZES = ["A4", "Letter", "Legal"];

const inputClass =
  "w-full rounded border border-line-strong bg-surface px-2 py-1.5 text-sm text-foreground";
const labelClass = "flex flex-col gap-1 text-xs text-muted";

/**
 * The Settings rail panel -- page-level settings (size/orientation/
 * margins/header/footer/page numbers), via the same priority-1
 * live-override mechanism PropertiesPanel uses for per-element styles
 * (backend: set_document_setting/clear_document_setting, targeting the
 * "Document" pseudo-target instead of one element's id) -- wins over
 * template/instructions and survives a reformat, same as any other
 * manual override.
 */
export function PageSettingsPanel() {
  const { document, change } = useDocumentEditor();
  const t = useI18n().m.edPanels.page;
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { settings } = document;

  async function run(action: (documentId: string) => Promise<Document>, fallback: string) {
    setPending(true);
    setError(null);
    try {
      await change(action);
    } catch (err) {
      setError(errorMessage(err, fallback));
    } finally {
      setPending(false);
    }
  }

  const apply = (property: FormattingProperty, value: string, unit?: string) =>
    run((documentId) => setPageSetting(documentId, { property, value, unit }), t.updateFailed);
  const reset = (property: FormattingProperty) => run((documentId) => clearPageSetting(documentId, property), t.resetFailed);

  const formKey = `${document.id}:${JSON.stringify(settings)}`;

  return (
    <fieldset key={formKey} disabled={pending} className="flex flex-col gap-4 text-sm">
      <div>
        <p className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t.page}</p>
        <div className="grid grid-cols-2 gap-2">
          <label className={labelClass}>
            {t.size}
            <select defaultValue={settings.pageSize} onChange={(e) => apply("pageSize", e.target.value)} className={inputClass}>
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
          <label className={labelClass}>
            {t.orientation}
            <select defaultValue={settings.orientation} onChange={(e) => apply("orientation", e.target.value)} className={inputClass}>
              <option value="portrait">{t.portrait}</option>
              <option value="landscape">{t.landscape}</option>
            </select>
          </label>
        </div>
      </div>

      <div>
        <p className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t.margins}</p>
        <div className="grid grid-cols-2 gap-2">
          <label className={labelClass}>
            {t.top}
            <input
              type="number"
              step="0.5"
              defaultValue={settings.marginTopCm}
              onBlur={(e) => e.target.value && apply("marginTop", e.target.value, "cm")}
              className={inputClass}
            />
          </label>
          <label className={labelClass}>
            {t.bottom}
            <input
              type="number"
              step="0.5"
              defaultValue={settings.marginBottomCm}
              onBlur={(e) => e.target.value && apply("marginBottom", e.target.value, "cm")}
              className={inputClass}
            />
          </label>
          <label className={labelClass}>
            {t.left}
            <input
              type="number"
              step="0.5"
              defaultValue={settings.marginLeftCm}
              onBlur={(e) => e.target.value && apply("marginLeft", e.target.value, "cm")}
              className={inputClass}
            />
          </label>
          <label className={labelClass}>
            {t.right}
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
        <p className="text-xs font-semibold tracking-wide text-muted uppercase">{t.headerFooter}</p>
        <label className={labelClass}>
          {t.headerText}
          <input
            type="text"
            defaultValue={settings.header ?? ""}
            onBlur={(e) => (e.target.value ? apply("header", e.target.value) : reset("header"))}
            className={inputClass}
          />
        </label>
        <label className={labelClass}>
          {t.footerText}
          <input
            type="text"
            defaultValue={settings.footer ?? ""}
            onBlur={(e) => (e.target.value ? apply("footer", e.target.value) : reset("footer"))}
            className={inputClass}
          />
        </label>
        <p className="text-xs text-muted">
          {t.fieldsBefore} <code className="rounded bg-surface-muted px-1 text-foreground">{"{PAGE}"}</code> {t.fieldsAnd}{" "}
          <code className="rounded bg-surface-muted px-1 text-foreground">{"{NUMPAGES}"}</code> {t.fieldsAfter}
        </p>
        <label className="flex items-center justify-between text-sm text-foreground">
          {t.pageNumbers}
          <input
            type="checkbox"
            defaultChecked={settings.showPageNumbers}
            onChange={(e) => apply("showPageNumbers", e.target.checked ? "true" : "false")}
            className="h-4 w-8 accent-accent"
          />
        </label>
      </div>

      {error && <p className="text-xs text-danger">{error}</p>}
    </fieldset>
  );
}
