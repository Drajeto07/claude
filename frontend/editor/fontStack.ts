import fallbacks from "./fontFallbacks.json";

/**
 * A document's font name as a CSS font-family list (tracker FONT-005): the font itself, then what
 * stands in for it where this computer doesn't have it -- the fonts made with its widths (Carlito
 * for Calibri, Liberation Sans for Arial), so its lines break as they would -- then the best fonts
 * of its kind, in the order a PDF export tries them, and last the generic family. The list is the
 * PDF export's own (app/export/fonts.py, written to fontFallbacks.json by
 * `python -m scripts.export_font_fallbacks`), so the pages here and a PDF stand in the same
 * fonts. The saved document keeps just the name (tiptapToDocument's normalizeFont takes the
 * first family).
 */

type Kind = keyof typeof fallbacks.kinds;

const GENERIC: Record<Kind, string> = { sans: "sans-serif", serif: "serif", mono: "monospace" };

/** "sans", "serif" or "mono": the kind of font a family name is, by its name (fonts.font_kind). */
export function fontKind(name: string): Kind {
  const lower = name.toLowerCase();
  if (fallbacks.hints.mono.some((hint) => lower.includes(hint))) return "mono";
  if (fallbacks.hints.serif.some((hint) => lower.includes(hint)) && !lower.includes("sans")) return "serif";
  return "sans";
}

/** The fonts that stand in for `name`, best first, after it (fonts.fallback_stack). */
export function fallbackStack(name: string): string[] {
  const compatible = Object.entries(fallbacks.metricCompatible).find(([family]) => family.toLowerCase() === name.toLowerCase())?.[1] ?? [];
  const stack = [name];
  for (const candidate of [...compatible, ...fallbacks.kinds[fontKind(name)]]) {
    if (!stack.some((each) => each.toLowerCase() === candidate.toLowerCase())) stack.push(candidate);
  }
  return stack;
}

// Each family's stack, once: every block of a document asks for its font's (PERF-005A).
const STACKS = new Map<string, string>();

export function cssFontStack(family: string): string {
  const known = STACKS.get(family);
  if (known !== undefined) return known;
  const name = family.trim().replace(/^["']|["']$/g, "");
  const stack = !name || name.includes(",") ? family : [...fallbackStack(name).map((each) => `"${each}"`), GENERIC[fontKind(name)]].join(", ");
  if (STACKS.size < 500) STACKS.set(family, stack); // a document names a few families; never grows without end
  return stack;
}
