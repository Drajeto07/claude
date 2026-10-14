import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/i18n/I18nProvider";
import type { DocumentSummary } from "@/types/document";

import { ProjectCard } from "./ProjectCard";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const project: DocumentSummary = {
  id: "doc 1",
  title: "Annual report",
  createdAt: "2026-10-10T10:00:00Z",
  updatedAt: "2026-10-13T12:00:00+00:00",
  formattedAt: null,
  status: "draft",
  sourceType: "uploaded_pdf",
  originalFilename: null,
  templateId: null,
  templateName: null,
};

function renderCard(locale: "en" | "bg" = "en") {
  return render(
    <I18nProvider locale={locale}>
      <ProjectCard project={project} />
    </I18nProvider>,
  );
}

describe("a project card's picture (real thumbnail, UI review 2026-10-14)", () => {
  it("asks for the project's own first page, one URL per version, loaded lazily", () => {
    renderCard();
    const img = screen.getByRole("img", { name: "First page of Annual report" });
    expect(img).toHaveAttribute("src", expect.stringContaining("/api/v1/documents/doc%201/thumbnail?v=2026-10-13T12%3A00%3A00%2B00%3A00"));
    expect(img).toHaveAttribute("loading", "lazy");
  });

  it("shows a quiet picture of its kind while the page loads, then the page", () => {
    renderCard();
    expect(screen.getByTestId("thumbnail-fallback")).toBeInTheDocument();
    const img = screen.getByRole("img", { name: "First page of Annual report" });
    expect(img.className).toContain("opacity-0");

    fireEvent.load(img);

    expect(screen.queryByTestId("thumbnail-fallback")).toBeNull();
    expect(img.className).toContain("opacity-100");
  });

  it("when the page can't be drawn: the picture of its kind stays, no broken image", () => {
    renderCard();
    fireEvent.error(screen.getByRole("img", { name: "First page of Annual report" }));

    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByTestId("thumbnail-fallback").querySelector("span")?.className).toContain("bg-tile-rose");  // a PDF's tint
  });

  it("names the page in the interface language", () => {
    renderCard("bg");
    expect(screen.getByRole("img", { name: "Първа страница на Annual report" })).toBeInTheDocument();
  });
});
