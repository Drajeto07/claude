import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/i18n/I18nProvider";

import { NewProject } from "./NewProject";
import { PROJECT_TYPES, suggestProjectType } from "./projectTypes";

const nav = vi.hoisted(() => ({ query: "" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(nav.query),
}));

afterEach(() => {
  nav.query = "";
});

describe("suggesting a type from a description (word match, not AI)", () => {
  it.each([
    ["A CV for a junior designer", "cv"],
    ["моето cv", "cv"],
    ["slides for Monday's meeting", "presentation"],
    ["презентация за проекта", "presentation"],
    ["a poster design for a concert", "poster"],
    ["покана за сватба", "invitation"],
    ["a flyer for the bakery", "brochure"],
    ["курсова работа по история", "document"],
    ["a report on renewable energy", "document"],
    ["an instagram post", "freeDesign"],
    ["something nice", null],
    ["", null],
  ])("%j -> %s", (description, expected) => {
    expect(suggestProjectType(description)).toBe(expected);
  });

  it("short keywords match whole words only ('cv' is not inside 'cvetan')", () => {
    expect(suggestProjectType("a letter to Cvetan")).toBe("document");
  });
});

function renderPage(locale: "en" | "bg" = "en") {
  return render(
    <I18nProvider locale={locale}>
      <NewProject />
    </I18nProvider>,
  );
}

describe("the New Project screen (S2-015)", () => {
  it("every type that starts today opens a real flow", () => {
    renderPage();
    const now = screen.getByRole("region", { name: "Start now" });
    expect(within(now).getByRole("link", { name: /Document/ })).toHaveAttribute("href", "/new");
    expect(within(now).getByRole("link", { name: /CV \/ Resume/ })).toHaveAttribute("href", "/new?template=professional-cv");
    expect(within(now).getByRole("link", { name: /Import a file/ })).toHaveAttribute("href", "/new?mode=upload");
    expect(within(now).getByRole("link", { name: /From a template/ })).toHaveAttribute("href", "/templates");
    expect(within(now).getByRole("link", { name: /Copy a document's look/ })).toHaveAttribute("href", "/new?reference=1");
  });

  it("the visual types are shown as coming, not as working", () => {
    renderPage();
    const later = screen.getByRole("region", { name: "Later in SmartDoc 2.0" });
    expect(within(later).queryAllByRole("link")).toHaveLength(0);
    for (const title of ["Presentation", "Brochure", "Invitation", "Poster", "Free design"]) {
      const card = within(later).getByText(title).closest("[aria-disabled]");
      expect(card, title).toHaveAttribute("aria-disabled", "true");
      expect(card).toHaveTextContent("Coming soon");
    }
    expect(PROJECT_TYPES.filter((type) => !type.href).length).toBe(5);
  });

  it("a description from the dashboard arrives filled in, with its suggestion marked", () => {
    nav.query = "describe=a%20CV%20for%20a%20designer";
    renderPage();
    expect(screen.getByLabelText("Describe what you want to create")).toHaveValue("a CV for a designer");
    expect(screen.getByRole("status")).toHaveTextContent("Suggested from your description: CV / Resume");
    expect(screen.getByRole("status")).toHaveTextContent("Picked from the words you typed");  // honest: not AI
    expect(screen.getByRole("link", { name: /CV \/ Resume/ })).toHaveAttribute("data-suggested", "true");
  });

  it("typing changes the suggestion; unknown words say so", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Describe what you want to create"), { target: { value: "a poster" } });
    expect(screen.getByRole("status")).toHaveTextContent("Poster");
    fireEvent.change(screen.getByLabelText("Describe what you want to create"), { target: { value: "hmm" } });
    expect(screen.getByRole("status")).toHaveTextContent("No type matches those words yet");
  });

  it("in Bulgarian", () => {
    renderPage("bg");
    expect(screen.getByRole("heading", { level: 1, name: "Създаване на проект" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /CV \/ Автобиография/ })).toHaveAttribute("href", "/new?template=professional-cv");
    expect(screen.getAllByText("Скоро").length).toBe(5);
  });
});
