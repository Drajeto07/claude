"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { DEFAULT_THEME, THEME_COOKIE, THEME_COOKIE_MAX_AGE, type Theme } from "./themes";

type ThemeState = { theme: Theme; setTheme: (theme: Theme) => void };

function apply(theme: Theme) {
  document.cookie = `${THEME_COOKIE}=${theme}; Path=/; Max-Age=${THEME_COOKIE_MAX_AGE}; SameSite=Lax`;
  document.documentElement.dataset.theme = theme;
}

const ThemeContext = createContext<ThemeState | null>(null);
const FALLBACK: ThemeState = { theme: DEFAULT_THEME, setTheme: apply };

/** The chosen theme, starting from the one the server rendered; switching needs no reload. */
export function ThemeProvider({ theme: initial, children }: { theme: Theme; children: ReactNode }) {
  const [theme, setState] = useState<Theme>(initial);
  const setTheme = useCallback((next: Theme) => {
    apply(next);
    setState(next);
  }, []);
  const value = useMemo(() => ({ theme, setTheme }), [theme, setTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  return useContext(ThemeContext) ?? FALLBACK;
}
