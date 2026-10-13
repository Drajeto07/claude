/**
 * Light or dark (UI review 2026-10-14): light is SmartDoc's look and the default; dark is a
 * choice in Settings or the sidebar -- never forced by the operating system. Remembered per
 * browser in a cookie so the server renders the first paint in it (no flash).
 */
export const THEMES = ["light", "dark"] as const;
export type Theme = (typeof THEMES)[number];
export const DEFAULT_THEME: Theme = "light";
export const THEME_COOKIE = "smartdoc_theme";
export const THEME_COOKIE_MAX_AGE = 365 * 24 * 60 * 60;

export function resolveTheme(cookieValue: string | null | undefined): Theme {
  return cookieValue === "dark" ? "dark" : DEFAULT_THEME;
}
