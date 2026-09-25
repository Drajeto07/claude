import type { CSSProperties } from "react";

import { cssFontStack } from "./fontStack";

/** One resolvedStyles entry (kebab-case CSS, as the backend engine produces it)
 * as a React style object -- for previews that render outside the editor. */
export function cssToStyle(css: Record<string, string> | undefined): CSSProperties {
  const style: Record<string, string> = {};
  for (const [property, value] of Object.entries(css ?? {})) {
    if (property.startsWith("--")) continue; // data such as --line-spacing, not display
    style[property.replace(/-([a-z])/g, (_, letter: string) => letter.toUpperCase())] = property === "font-family" ? cssFontStack(value) : value;
  }
  return style as CSSProperties;
}
