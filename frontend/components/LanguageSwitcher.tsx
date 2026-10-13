"use client";

import { Languages } from "lucide-react";

import { useI18n } from "@/i18n/I18nProvider";
import { format, LOCALES, type Locale } from "@/i18n/locales";

/**
 * Switches the interface language (D-010). `compact`: two small buttons for the sign-in pages;
 * otherwise a labelled radio group for Settings. Either way the choice is remembered.
 */
export function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  const { locale, m, setLocale } = useI18n();
  const name = (code: Locale) => m.language[code];

  if (compact) {
    return (
      <div className="inline-flex items-center gap-1 rounded-xl border border-line bg-surface p-1 shadow-sm" role="group" aria-label={m.language.label}>
        <Languages className="ml-1.5 h-4 w-4 text-muted" aria-hidden="true" />
        {LOCALES.map((code) => (
          <button
            key={code}
            type="button"
            lang={code}
            onClick={() => setLocale(code)}
            aria-pressed={locale === code}
            title={format(m.language.switchTo, { language: name(code) })}
            className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
              locale === code ? "bg-accent text-accent-foreground" : "text-muted hover:bg-surface-muted hover:text-foreground"
            }`}
          >
            {name(code)}
          </button>
        ))}
      </div>
    );
  }

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="text-sm font-medium text-foreground">{m.language.label}</legend>
      <p className="text-xs text-muted">{m.language.hint}</p>
      <div className="mt-1 flex flex-wrap gap-2">
        {LOCALES.map((code) => (
          <label
            key={code}
            lang={code}
            className={`flex cursor-pointer items-center gap-2 rounded-xl border px-3.5 py-2 text-sm transition-colors ${
              locale === code ? "border-accent bg-accent/5 text-foreground" : "border-line bg-surface text-muted hover:text-foreground"
            }`}
          >
            <input type="radio" name="interface-language" value={code} checked={locale === code} onChange={() => setLocale(code)} className="accent-[var(--accent)]" />
            {name(code)}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
