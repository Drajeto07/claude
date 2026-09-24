import type { CSSProperties } from "react";

/** One resolvedStyles entry (kebab-case CSS, as the backend engine produces it)
 * as a React style object -- for previews that render outside the editor. */
export function cssToStyle(css: Record<string, string> | undefined): CSSProperties {
  const style: Record<string, string> = {};
  for (const [property, value] of Object.entries(css ?? {})) {
    style[property.replace(/-([a-z])/g, (_, letter: string) => letter.toUpperCase())] = value;
  }
  return style as CSSProperties;
}
