import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";

import { formatRelative } from "./format";
import { I18nProvider, useI18n } from "./I18nProvider";
import { format, LOCALE_COOKIE, negotiateLocale, resolveLocale } from "./locales";
import { bg } from "./messages/bg";
import { en } from "./messages/en";

const router = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

afterEach(() => {
  document.cookie = `${LOCALE_COOKIE}=; Path=/; Max-Age=0`;
  document.documentElement.lang = "en";
  router.refresh.mockReset();
});

describe("which interface language a visit starts in (D-010)", () => {
  it.each([
    ["bg", "bg"],
    ["bg-BG,bg;q=0.9,en;q=0.8", "bg"],
    ["BG-bg", "bg"],
    ["en-US,en;q=0.9,bg;q=0.8", "en"],
    ["de-DE,de;q=0.9", "en"],
    ["en;q=0.5,bg;q=0.9", "bg"],  // the highest preference wins, not the first listed
    ["*", "en"],
    ["", "en"],
    [null, "en"],
  ])("Accept-Language %j -> %s", (header, expected) => {
    expect(negotiateLocale(header)).toBe(expected);
  });

  it("a stored choice wins over the browser's language; a bad cookie value is ignored", () => {
    expect(resolveLocale("en", "bg-BG")).toBe("en");
    expect(resolveLocale("bg", "en-US")).toBe("bg");
    expect(resolveLocale("fr", "bg-BG")).toBe("bg");
    expect(resolveLocale(undefined, "en-GB")).toBe("en");
  });
});

type Tree = { [key: string]: Tree | string | readonly Tree[] };

function leaves(tree: unknown, path = ""): [string, string][] {
  if (typeof tree === "string") return [[path, tree]];
  if (Array.isArray(tree)) return tree.flatMap((item, index) => leaves(item, `${path}[${index}]`));
  return Object.entries(tree as Tree).flatMap(([key, value]) => leaves(value, path ? `${path}.${key}` : key));
}

describe("the dictionaries", () => {
  const enLeaves = new Map(leaves(en));
  const bgLeaves = new Map(leaves(bg));

  it("Bulgarian has every English key and no others", () => {
    expect([...bgLeaves.keys()].sort()).toEqual([...enLeaves.keys()].sort());
  });

  it("no text is empty, and every text keeps the English placeholders", () => {
    for (const [key, english] of enLeaves) {
      const bulgarian = bgLeaves.get(key) ?? "";
      expect(bulgarian.trim(), key).not.toBe("");
      const placeholders = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort();
      expect(placeholders(bulgarian), key).toEqual(placeholders(english));
    }
  });

  it("the Bulgarian really is Bulgarian where words are involved", () => {
    expect(bg.auth.login.title).toBe("Вход");
    expect(/[а-я]/i.test(bg.dashboard.welcome)).toBe(true);
  });

  it("fills placeholders and leaves unknown ones visible", () => {
    expect(format(en.dashboard.welcomeName, { name: "Dana" })).toBe("Welcome back, Dana");
    expect(format("{a} and {b}", { a: 1 })).toBe("1 and {b}");
  });

  it("reads a server time without a zone as UTC, not as the browser's local time", () => {
    const now = new Date("2026-10-13T20:00:30Z");
    expect(formatRelative("2026-10-13T20:00:00", "en", now)).toBe("now");  // SQLite: no zone
    expect(formatRelative("2026-10-13T20:00:00Z", "en", now)).toBe("now");
    expect(formatRelative("2026-10-13T23:00:00+03:00", "en", now)).toBe("now");
  });

  it("says 'how long ago' in each language", () => {
    const now = new Date("2026-10-13T12:00:00Z");
    expect(formatRelative("2026-10-13T11:55:00Z", "en", now)).toBe("5 minutes ago");
    expect(formatRelative("2026-10-13T11:55:00Z", "bg", now)).toBe("преди 5 минути");
    expect(formatRelative("2026-10-12T12:00:00Z", "bg", now)).toBe("вчера");
  });
});

function Probe() {
  const { m, locale } = useI18n();
  return (
    <p>
      {locale}: {m.shell.projects}
    </p>
  );
}

describe("switching the interface language", () => {
  it("changes the words at once, remembers the choice for a year and refreshes the server parts", () => {
    render(
      <I18nProvider locale="en">
        <Probe />
        <LanguageSwitcher compact />
      </I18nProvider>,
    );
    expect(screen.getByText("en: Projects")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Български" }));

    expect(screen.getByText("bg: Проекти")).toBeInTheDocument();
    expect(document.cookie).toContain(`${LOCALE_COOKIE}=bg`);
    expect(document.documentElement.lang).toBe("bg");
    expect(router.refresh).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Български" })).toHaveAttribute("aria-pressed", "true");
    // The group is labelled in the new language too.
    expect(screen.getByRole("group", { name: "Език на интерфейса" })).toBeInTheDocument();
  });

  it("starts in Bulgarian when the server resolved Bulgarian, and the Settings radio group switches back", () => {
    render(
      <I18nProvider locale="bg">
        <Probe />
        <LanguageSwitcher />
      </I18nProvider>,
    );
    expect(screen.getByText("bg: Проекти")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Български" })).toBeChecked();

    fireEvent.click(screen.getByRole("radio", { name: "English" }));

    expect(screen.getByText("en: Projects")).toBeInTheDocument();
    expect(document.cookie).toContain(`${LOCALE_COOKIE}=en`);
  });

  it("outside a provider, components speak English", () => {
    render(<Probe />);
    expect(screen.getByText("en: Projects")).toBeInTheDocument();
  });
});
