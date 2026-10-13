"use client";

import { Moon, Sun } from "lucide-react";

import { useI18n } from "@/i18n/I18nProvider";
import { useTheme } from "@/theme/ThemeProvider";
import { THEMES } from "@/theme/themes";

/**
 * Light or dark. `compact`: one icon button that flips it (the sidebar); otherwise a labelled
 * radio group (Settings). Either way the choice is remembered on this browser.
 */
export function ThemeSwitcher({ compact = false }: { compact?: boolean }) {
  const { theme, setTheme } = useTheme();
  const { m } = useI18n();

  if (compact) {
    const next = theme === "dark" ? "light" : "dark";
    const label = next === "dark" ? m.theme.toDark : m.theme.toLight;
    return (
      <button
        type="button"
        onClick={() => setTheme(next)}
        aria-label={label}
        title={label}
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        {theme === "dark" ? <Sun className="h-4 w-4" aria-hidden="true" /> : <Moon className="h-4 w-4" aria-hidden="true" />}
      </button>
    );
  }

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="text-sm font-medium text-foreground">{m.theme.label}</legend>
      <p className="text-xs text-muted">{m.theme.hint}</p>
      <div className="mt-1 flex flex-wrap gap-2">
        {THEMES.map((option) => {
          const Icon = option === "dark" ? Moon : Sun;
          return (
            <label
              key={option}
              className={`flex cursor-pointer items-center gap-2 rounded-xl border px-3.5 py-2 text-sm transition-colors ${
                theme === option ? "border-accent bg-accent-soft text-foreground" : "border-line bg-surface text-muted hover:text-foreground"
              }`}
            >
              <input type="radio" name="interface-theme" value={option} checked={theme === option} onChange={() => setTheme(option)} className="accent-[var(--accent)]" />
              <Icon className="h-4 w-4" aria-hidden="true" />
              {m.theme[option]}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
