import type { Locale } from "./locales";

/**
 * A time from the API. The API means UTC, but a database that keeps no time zone (SQLite in
 * development and the end-to-end tests) sends it without one, and `new Date()` would then read
 * it as local time -- "edited 3 hours ago" for something just made, in Sofia. No zone: UTC.
 */
export function parseServerTime(iso: string): Date {
  return new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso) || !iso.includes("T") ? iso : `${iso}Z`);
}

/**
 * "5 minutes ago" / "преди 5 минути" in the interface language (Intl, no word lists of our own):
 * relative up to a week, then the date.
 */
export function formatRelative(iso: string, locale: Locale, now: Date = new Date()): string {
  const then = parseServerTime(iso);
  const seconds = Math.round((then.getTime() - now.getTime()) / 1000);
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const abs = Math.abs(seconds);
  if (abs < 45) return rtf.format(0, "second");
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), "minute");
  if (abs < 86_400) return rtf.format(Math.round(seconds / 3600), "hour");
  if (abs < 7 * 86_400) return rtf.format(Math.round(seconds / 86_400), "day");
  return formatDate(iso, locale);
}

export function formatDate(iso: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric" }).format(parseServerTime(iso));
}

export function formatDateTime(iso: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(parseServerTime(iso));
}
