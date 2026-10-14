import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ThemeSwitcher } from "@/components/ThemeSwitcher";

import { ThemeProvider, useTheme } from "./ThemeProvider";
import { resolveTheme, THEME_COOKIE } from "./themes";

afterEach(() => {
  document.cookie = `${THEME_COOKIE}=; Path=/; Max-Age=0`;
  delete document.documentElement.dataset.theme;
});

function Probe() {
  return <p>theme: {useTheme().theme}</p>;
}

describe("light or dark (UI review 2026-10-14)", () => {
  it("light unless this browser chose dark -- never the operating system's setting", () => {
    expect(resolveTheme(undefined)).toBe("light");
    expect(resolveTheme("")).toBe("light");
    expect(resolveTheme("dark")).toBe("dark");
    expect(resolveTheme("blue")).toBe("light");
  });

  it("Settings: choosing dark applies it at once and remembers it for a year", () => {
    render(
      <ThemeProvider theme="light">
        <Probe />
        <ThemeSwitcher />
      </ThemeProvider>,
    );
    expect(screen.getByRole("radio", { name: "Light" })).toBeChecked();

    fireEvent.click(screen.getByRole("radio", { name: "Dark" }));

    expect(screen.getByText("theme: dark")).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.cookie).toContain(`${THEME_COOKIE}=dark`);
  });

  it("the sidebar button flips it and says what it will do", () => {
    render(
      <ThemeProvider theme="dark">
        <Probe />
        <ThemeSwitcher compact />
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Switch to the light theme" }));

    expect(screen.getByText("theme: light")).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(screen.getByRole("button", { name: "Switch to the dark theme" })).toBeInTheDocument();
  });
});
