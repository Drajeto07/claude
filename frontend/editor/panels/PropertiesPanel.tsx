"use client";

import { AlignCenter, AlignJustify, AlignLeft, AlignRight, Bold, Italic, RotateCcw, Underline as UnderlineIcon } from "lucide-react";
import { cloneElement, useId, useState, type ReactElement, type ReactNode } from "react";

import { useDocumentEditor } from "@/editor/EditorState";
import { PictureControls } from "@/editor/panels/PictureControls";
import { useI18n } from "@/i18n/I18nProvider";
import { clearElementStyle, errorMessage, setElementStyle } from "@/services/api";
import type { Document, Element, FormattingProperty } from "@/types/document";

const FONT_FAMILIES = ["Arial", "Times New Roman", "Calibri", "Georgia", "Courier New"];

const inputClass =
  "w-full rounded border border-line-strong bg-surface px-2 py-1.5 text-sm text-foreground";

function currentCss(document: Document, element: Element): Record<string, string> {
  return element.styleRef ? (document.resolvedStyles[element.styleRef] ?? {}) : {};
}

function imageAlignmentFromCss(css: Record<string, string>): string {
  if (css["margin-left"] === "auto" && css["margin-right"] === "auto") return "center";
  if (css["margin-left"] === "auto") return "right";
  return "left";
}

function Row({ label, onReset, children }: { label: string; onReset: () => void; children: ReactElement<{ id?: string }> }) {
  const t = useI18n().m.edPanels.properties;
  const id = useId();
  // The reset is a small icon beside the label, outside it: a long label ("Междуредие") keeps its room,
  // and the field's name is the label alone.
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="flex items-start justify-between gap-1 text-xs text-muted">
        <label htmlFor={id} className="min-w-0 break-words">
          {label}
        </label>
        <button
          type="button"
          onClick={onReset}
          title={t.resetTitle}
          aria-label={`${t.resetTitle}: ${label}`}
          className="shrink-0 rounded p-0.5 text-muted hover:text-accent"
        >
          <RotateCcw className="h-3 w-3" aria-hidden="true" />
        </button>
      </span>
      {cloneElement(children, { id })}
    </div>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return <p className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{children}</p>;
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
        active ? "bg-accent/10 text-accent" : "text-muted hover:bg-surface-muted"
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
 * Lives in the Properties sidebar, grouped into Text/Paragraph sections.
 */
export function PropertiesPanel() {
  const { document, selection, change } = useDocumentEditor();
  const t = useI18n().m.edPanels.properties;
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const element = selection.selectedElement;

  if (!element) {
    return <p className="text-sm text-muted">{t.selectFirst}</p>;
  }
  const elementId = element.id;

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
    run((documentId) => setElementStyle(documentId, elementId, { property, value, unit }), t.updateFailed);
  const reset = (property: FormattingProperty) =>
    run((documentId) => clearElementStyle(documentId, elementId, property), t.resetFailed);

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
      <p className="text-xs font-semibold tracking-wide text-muted uppercase">{(t.types as Record<string, string>)[element.type] ?? element.type}</p>

      {isImage ? (
        <div>
          <SectionLabel>{t.image}</SectionLabel>
          <div className="flex flex-col gap-3">
            <Row label={t.widthPercent} onReset={() => reset("imageWidth")}>
              <input
                type="number"
                defaultValue={css["width"]?.replace(/%$/, "") ?? ""}
                onBlur={(e) => e.target.value && apply("imageWidth", e.target.value, "%")}
                className={inputClass}
              />
            </Row>
            <Row label={t.alignment} onReset={() => reset("imageAlignment")}>
              <select defaultValue={imageAlignmentFromCss(css)} onChange={(e) => apply("imageAlignment", e.target.value)} className={inputClass}>
                <option value="left">{t.left}</option>
                <option value="center">{t.center}</option>
                <option value="right">{t.right}</option>
              </select>
            </Row>
          </div>
          <div className="mt-4">
            <SectionLabel>{t.cropTurn}</SectionLabel>
            <PictureControls elementId={element.id} />
          </div>
        </div>
      ) : (
        <>
          <div>
            <SectionLabel>{t.text}</SectionLabel>
            <div className="flex flex-col gap-3">
              <div className="grid grid-cols-2 gap-2">
                <Row label={t.fontFamily} onReset={() => reset("fontFamily")}>
                  <select defaultValue={css["font-family"] ?? ""} onChange={(e) => e.target.value && apply("fontFamily", e.target.value)} className={inputClass}>
                    <option value="">–</option>
                    {FONT_FAMILIES.map((font) => (
                      <option key={font} value={font}>
                        {font}
                      </option>
                    ))}
                  </select>
                </Row>
                <Row label={t.sizePt} onReset={() => reset("fontSize")}>
                  <input
                    type="number"
                    defaultValue={css["font-size"]?.replace(/pt$/, "") ?? ""}
                    onBlur={(e) => e.target.value && apply("fontSize", e.target.value, "pt")}
                    className={inputClass}
                  />
                </Row>
              </div>

              <div className="flex items-center gap-1">
                <ToggleIconButton label={t.bold} active={css["font-weight"] === "bold"} onClick={() => apply("bold", css["font-weight"] === "bold" ? "false" : "true")}>
                  <Bold className="h-4 w-4" aria-hidden="true" />
                </ToggleIconButton>
                <ToggleIconButton label={t.italic} active={css["font-style"] === "italic"} onClick={() => apply("italic", css["font-style"] === "italic" ? "false" : "true")}>
                  <Italic className="h-4 w-4" aria-hidden="true" />
                </ToggleIconButton>
                <ToggleIconButton
                  label={t.underline}
                  active={css["text-decoration"] === "underline"}
                  onClick={() => apply("underline", css["text-decoration"] === "underline" ? "false" : "true")}
                >
                  <UnderlineIcon className="h-4 w-4" aria-hidden="true" />
                </ToggleIconButton>
                <span className="mx-1 h-6 w-px bg-line" aria-hidden="true" />
                <input
                  type="text"
                  title={t.textColor}
                  aria-label={t.textColor}
                  placeholder="#000000"
                  defaultValue={css["color"] ?? ""}
                  onBlur={(e) => e.target.value && apply("color", e.target.value)}
                  className="h-8 w-24 rounded border border-line-strong bg-surface px-2 text-xs text-foreground"
                />
              </div>

              <div className="flex items-center gap-1">
                <ToggleIconButton label={t.alignLeft} active={css["text-align"] === "left"} onClick={() => apply("alignment", "left")}>
                  <AlignLeft className="h-4 w-4" aria-hidden="true" />
                </ToggleIconButton>
                <ToggleIconButton label={t.alignCenter} active={css["text-align"] === "center"} onClick={() => apply("alignment", "center")}>
                  <AlignCenter className="h-4 w-4" aria-hidden="true" />
                </ToggleIconButton>
                <ToggleIconButton label={t.alignRight} active={css["text-align"] === "right"} onClick={() => apply("alignment", "right")}>
                  <AlignRight className="h-4 w-4" aria-hidden="true" />
                </ToggleIconButton>
                <ToggleIconButton label={t.justify} active={css["text-align"] === "justify"} onClick={() => apply("alignment", "justify")}>
                  <AlignJustify className="h-4 w-4" aria-hidden="true" />
                </ToggleIconButton>
              </div>
            </div>
          </div>

          <div>
            <SectionLabel>{t.paragraph}</SectionLabel>
            <div className="grid grid-cols-2 gap-2">
              <Row label={t.lineSpacing} onReset={() => reset("lineSpacing")}>
                <input type="number" step="0.05" defaultValue={css["--line-spacing"] ?? css["line-height"] ?? ""} onBlur={(e) => e.target.value && apply("lineSpacing", e.target.value)} className={inputClass} />
              </Row>
              <Row label={t.spaceAfter} onReset={() => reset("paragraphSpacing")}>
                <input
                  type="number"
                  defaultValue={css["margin-bottom"]?.replace(/pt$/, "") ?? ""}
                  onBlur={(e) => e.target.value && apply("paragraphSpacing", e.target.value, "pt")}
                  className={inputClass}
                />
              </Row>
              <Row label={t.firstLine} onReset={() => reset("firstLineIndent")}>
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

      {error && <p className="text-xs text-danger">{error}</p>}
    </fieldset>
  );
}
