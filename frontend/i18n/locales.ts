/**
 * The interface languages of SmartDoc 2.0 (D-010): Bulgarian and English. This is the language
 * of the app's own words only -- never of a document's text or of what Translate produces.
 *
 * The choice lives in a cookie, so the server renders the first paint in it (no flash of the
 * other language) and it lasts between visits on this browser. Without a choice, the browser's
 * preferred language decides: Bulgarian for "bg", English for anything else.
 */
export const LOCALES = ["en", "bg"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";
export const LOCALE_COOKIE = "smartdoc_locale";
export const LOCALE_COOKIE_MAX_AGE = 365 * 24 * 60 * 60;

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (LOCALES as readonly string[]).includes(value);
}

/**
 * The language to start in from an Accept-Language header (or navigator.languages joined): the
 * entry the browser prefers most (highest q, first on a tie) decides -- "bg" or "bg-BG" gives
 * Bulgarian, anything else English.
 */
export function negotiateLocale(acceptLanguage: string | null | undefined): Locale {
  if (!acceptLanguage) return DEFAULT_LOCALE;
  let best: { tag: string; q: number; index: number } | null = null;
  acceptLanguage.split(",").forEach((part, index) => {
    const [rawTag, ...params] = part.trim().split(";");
    const tag = rawTag.trim().toLowerCase();
    if (!tag) return;
    const qParam = params.map((p) => p.trim()).find((p) => p.startsWith("q="));
    const q = qParam ? Number(qParam.slice(2)) : 1;
    if (!Number.isFinite(q) || q <= 0) return;
    if (!best || q > best.q) best = { tag, q, index };
  });
  const chosen = best as { tag: string } | null;
  return chosen && chosen.tag.split("-")[0] === "bg" ? "bg" : "en";
}

/** The locale a stored cookie value names, else what the browser prefers. */
export function resolveLocale(cookieValue: string | null | undefined, acceptLanguage: string | null | undefined): Locale {
  return isLocale(cookieValue) ? cookieValue : negotiateLocale(acceptLanguage);
}

/** Fills {name} placeholders: format("Hello, {name}", { name: "Dana" }). */
export function format(template: string, values: Record<string, string | number> = {}): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) => (key in values ? String(values[key]) : match));
}

/** A count in words: `forms.one` for exactly one, `forms.other` otherwise (both languages need only
 * these two), with {count} filled in: plural(2, { one: "{count} file", other: "{count} files" }). */
export function plural(count: number, forms: { one: string; other: string }, values: Record<string, string | number> = {}): string {
  return format(count === 1 ? forms.one : forms.other, { count, ...values });
}
