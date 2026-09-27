import { Extension } from "@tiptap/core";

import type { Mark } from "@/types/document";

/**
 * Word's character formatting beyond bold, italic and plain lines (tracker DOCX-013),
 * as attributes on the marks the editor already has:
 * - underline `lineStyle`: double, thick, dotted, dashed or wavy;
 * - strike `lineStyle`: double;
 * - textStyle `caps`, `smallCaps`, `letterSpacing` and `baselineShift` (a raised or
 *   lowered baseline).
 * Pasted HTML is read the same way, Word's own CSS included (`text-underline`, a
 * raised run's `position: relative; top`), so its formatting survives a paste.
 */

export type LineStyle = NonNullable<Mark["lineStyle"]>;
export const LINE_STYLES: readonly LineStyle[] = ["double", "thick", "dotted", "dashed", "wavy"];

// Word's clipboard names for its underline styles (mso "text-underline").
const WORD_UNDERLINES: Record<string, LineStyle> = {
  double: "double",
  thick: "thick",
  dotted: "dotted",
  "dotted-heavy": "dotted",
  dash: "dashed",
  "dashed-heavy": "dashed",
  "dash-long": "dashed",
  "dot-dash": "dashed",
  "dot-dot-dash": "dashed",
  wave: "wavy",
  "wavy-heavy": "wavy",
  "wavy-double": "wavy",
};

/** A CSS property of an element's inline style, whether or not the browser knows it. */
function cssValue(element: HTMLElement, property: string): string {
  const known = element.style.getPropertyValue(property).trim();
  if (known) return known.toLowerCase();
  const match = (element.getAttribute("style") ?? "").match(new RegExp(`(?:^|;)\\s*${property}\\s*:\\s*([^;]+)`, "i"));
  return match ? match[1].trim().toLowerCase() : "";
}

function underlineStyle(element: HTMLElement): LineStyle | null {
  const own = element.getAttribute("data-line-style");
  if (own && (LINE_STYLES as readonly string[]).includes(own)) return own as LineStyle;
  const word = WORD_UNDERLINES[cssValue(element, "text-underline")];
  if (word) return word;
  const decoration = [cssValue(element, "text-decoration-style"), ...cssValue(element, "text-decoration").split(/\s+/)];
  const style = decoration.find((value) => ["double", "dotted", "dashed", "wavy"].includes(value));
  if (style) return style as LineStyle;
  const thickness = cssValue(element, "text-decoration-thickness");
  return thickness && !["auto", "from-font"].includes(thickness) ? "thick" : null;
}

const LINE_CSS: Record<LineStyle, string> = {
  double: "text-decoration-style: double",
  thick: "text-decoration-thickness: 0.14em",
  dotted: "text-decoration-style: dotted",
  dashed: "text-decoration-style: dashed",
  wavy: "text-decoration-style: wavy",
};

function lineStyleAttribute(allowed: readonly LineStyle[]) {
  return {
    default: null,
    parseHTML: (element: HTMLElement) => {
      const style = underlineStyle(element);
      return style && allowed.includes(style) ? style : null;
    },
    renderHTML: (attributes: Record<string, unknown>) => {
      const style = attributes.lineStyle as LineStyle | null;
      return style && allowed.includes(style) ? { "data-line-style": style, style: LINE_CSS[style] } : {};
    },
  };
}

/** A raised or lowered baseline, from `vertical-align: 3pt` or Word's `position: relative; top: -3pt`. */
function baselineShift(element: HTMLElement): string | null {
  const align = cssValue(element, "vertical-align");
  if (/^-?\d+(\.\d+)?(pt|px)$/.test(align)) return align;
  const top = cssValue(element, "top");
  if (cssValue(element, "position") === "relative" && /^-?\d+(\.\d+)?(pt|px)$/.test(top)) {
    return top.startsWith("-") ? top.slice(1) : `-${top}`;
  }
  return null;
}

export const CharacterFormatting = Extension.create({
  name: "characterFormatting",

  addGlobalAttributes() {
    return [
      { types: ["underline"], attributes: { lineStyle: lineStyleAttribute(LINE_STYLES) } },
      { types: ["strike"], attributes: { lineStyle: lineStyleAttribute(["double"]) } },
      {
        types: ["textStyle"],
        attributes: {
          caps: {
            default: null,
            parseHTML: (element: HTMLElement) => (cssValue(element, "text-transform") === "uppercase" ? true : null),
            renderHTML: (attributes: Record<string, unknown>) => (attributes.caps ? { style: "text-transform: uppercase" } : {}),
          },
          smallCaps: {
            default: null,
            parseHTML: (element: HTMLElement) =>
              cssValue(element, "font-variant") === "small-caps" || cssValue(element, "font-variant-caps") === "small-caps" ? true : null,
            renderHTML: (attributes: Record<string, unknown>) => (attributes.smallCaps ? { style: "font-variant-caps: small-caps" } : {}),
          },
          letterSpacing: {
            default: null,
            parseHTML: (element: HTMLElement) => cssValue(element, "letter-spacing") || null,
            renderHTML: (attributes: Record<string, unknown>) =>
              attributes.letterSpacing ? { style: `letter-spacing: ${attributes.letterSpacing as string}` } : {},
          },
          baselineShift: {
            default: null,
            parseHTML: baselineShift,
            renderHTML: (attributes: Record<string, unknown>) =>
              attributes.baselineShift ? { style: `vertical-align: ${attributes.baselineShift as string}` } : {},
          },
        },
      },
    ];
  },
});
