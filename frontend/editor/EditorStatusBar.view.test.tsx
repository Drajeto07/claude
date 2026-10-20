import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/i18n/I18nProvider";
import type { Locale } from "@/i18n/locales";

import { EditorStatusBar } from "./EditorStatusBar";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }), usePathname: () => "/" }));

function bar(locale: Locale, view?: { flow: boolean; onChange: (flow: boolean) => void }) {
  return render(
    <I18nProvider locale={locale}>
      <EditorStatusBar
        zoom={0.75}
        onZoomChange={() => undefined}
        onFitWidth={() => undefined}
        pageCount={3}
        onAddPage={() => undefined}
        saveStatus="saved"
        onRetrySave={() => undefined}
        view={view}
      />
    </I18nProvider>,
  );
}

describe("the classic editor's view switch on a phone (S2-096B)", () => {
  it("is not there without a view (desktop, the 2.0 editor): page count and zoom as before", () => {
    bar("en");
    expect(screen.queryByRole("group", { name: "View" })).toBeNull();
    expect(screen.getByText("3 pages")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeInTheDocument();
  });

  it("in the writing view leaves out the page count and the zoom, and switches to Page", () => {
    const onChange = vi.fn();
    bar("en", { flow: true, onChange });
    expect(screen.getByRole("button", { name: "Writing" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("3 pages")).toBeNull();
    expect(screen.queryByRole("button", { name: "Zoom in" })).toBeNull();
    screen.getByRole("button", { name: "Page" }).click();
    expect(onChange).toHaveBeenCalledWith(false);
  });

  it("in the page view keeps the page count and the zoom", () => {
    bar("en", { flow: false, onChange: () => undefined });
    expect(screen.getByRole("button", { name: "Page" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("3 pages")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fit width" })).toBeInTheDocument();
  });

  it("speaks Bulgarian when the interface does", () => {
    bar("bg", { flow: true, onChange: () => undefined });
    expect(screen.getByRole("group", { name: "Изглед" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Писане" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Страница" })).toHaveAttribute("aria-pressed", "false");
  });
});
