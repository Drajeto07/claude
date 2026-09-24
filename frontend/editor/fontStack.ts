const MONO_HINTS = ["mono", "courier", "consolas", "code", "menlo", "monaco", "typewriter", "console"];
const SERIF_HINTS = ["times", "georgia", "cambria", "garamond", "antiqua", "palatino", "serif", "roman", "book", "minion", "baskerville", "didot", "constantia"];

/**
 * A document's font name as a CSS font-family list with the right generic
 * fallback, so a font this computer doesn't have (Aptos, say) still shows as
 * the same kind of font instead of the browser's default serif. The saved
 * document keeps just the name (tiptapToDocument's normalizeFont takes the
 * first family).
 */
export function cssFontStack(family: string): string {
  const name = family.trim().replace(/^["']|["']$/g, "");
  if (!name || name.includes(",")) return family; // already a list
  const lower = name.toLowerCase();
  const generic = MONO_HINTS.some((hint) => lower.includes(hint))
    ? "monospace"
    : SERIF_HINTS.some((hint) => lower.includes(hint)) && !lower.includes("sans")
      ? "serif"
      : "sans-serif";
  return `"${name}", ${generic}`;
}
