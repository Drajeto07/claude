"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { DEFAULT_LOCALE, LOCALE_COOKIE, LOCALE_COOKIE_MAX_AGE, type Locale } from "./locales";
import { messagesFor } from "./messages";
import type { Messages } from "./messages/en";

type I18n = { locale: Locale; m: Messages; setLocale: (locale: Locale) => void };

const I18nContext = createContext<I18n | null>(null);

/** Remembers the choice on this browser for a year (read by the server on the next request). */
export function storeLocale(locale: Locale) {
  document.cookie = `${LOCALE_COOKIE}=${locale}; Path=/; Max-Age=${LOCALE_COOKIE_MAX_AGE}; SameSite=Lax`;
}

/**
 * The interface language for client components, starting from the one the server resolved
 * (cookie, else the browser's language). Switching stores the choice, updates <html lang>,
 * and refreshes the server-rendered parts so they speak it too.
 */
export function I18nProvider({ locale: initial, children }: { locale: Locale; children: ReactNode }) {
  const router = useRouter();
  const [locale, setState] = useState<Locale>(initial);

  const setLocale = useCallback(
    (next: Locale) => {
      storeLocale(next);
      document.documentElement.lang = next;
      setState(next);
      router.refresh();
    },
    [router],
  );

  const value = useMemo(() => ({ locale, m: messagesFor(locale), setLocale }), [locale, setLocale]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

// Outside a provider (a component rendered on its own, e.g. in a unit test): English, and a
// switch that only stores the choice. Every page has the provider (app/layout.tsx).
const FALLBACK: I18n = { locale: DEFAULT_LOCALE, m: messagesFor(DEFAULT_LOCALE), setLocale: (locale) => storeLocale(locale) };

/** The current language's messages (`m.dashboard.title`), the locale, and a way to switch. */
export function useI18n(): I18n {
  return useContext(I18nContext) ?? FALLBACK;
}
