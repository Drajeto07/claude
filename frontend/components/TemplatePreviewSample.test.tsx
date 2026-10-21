import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { TemplatePreviewSample } from "@/components/TemplatePreviewSample";
import { StylePreviewPage } from "@/components/templates/StylePreviewPage";
import { I18nProvider } from "@/i18n/I18nProvider";
import { bg } from "@/i18n/messages/bg";
import { en } from "@/i18n/messages/en";
import type { StylePreview } from "@/types/document";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: () => undefined }) }));
// jsdom has no ResizeObserver; the sample page only uses it to scale itself to its column.
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    disconnect() {}
  },
);

/**
 * S2-098: the sample text template previews are drawn with speaks the interface's language; the template's look
 * (its resolved styles) and its own words (header, footer) are what they were.
 */

const STYLES = {
  "Heading 1": { "font-family": "Georgia, serif", "font-size": "20pt", color: "#1f3864" },
  "Heading 2": { "font-family": "Georgia, serif", "font-size": "14pt" },
  Paragraph: { "font-family": "Calibri, Carlito, sans-serif", "font-size": "11pt", "line-height": "1.5", "text-align": "justify" },
};

const PREVIEW = {
  resolvedStyles: STYLES,
  settings: {
    pageSize: "A4",
    orientation: "portrait",
    pageWidthMm: 210,
    pageHeightMm: 297,
    marginTopCm: 2,
    marginRightCm: 2,
    marginBottomCm: 2,
    marginLeftCm: 3,
    header: "Годишен отчет",
    footer: "Фирма ООД",
    showPageNumbers: true,
  },
} as unknown as StylePreview;

const inLanguage = (locale: "en" | "bg", children: ReactNode) => render(<I18nProvider locale={locale}>{children}</I18nProvider>);

const CYRILLIC = /[\u0400-\u04FF]/;
const strings = (value: unknown): string[] => (typeof value === "string" ? [value] : Object.values(value as object).flatMap(strings));

describe("TemplatePreviewSample (the card)", () => {
  it.each([
    ["en", en],
    ["bg", bg],
  ] as const)("in %s: the sample words of that language, in the template's own look", (locale, m) => {
    const { container } = inLanguage(locale, <TemplatePreviewSample styles={STYLES} />);
    const heading = container.querySelector("h1")!;
    expect(heading).toHaveTextContent(m.templateSamples.card.heading);
    expect(container.querySelector("h2")).toHaveTextContent(m.templateSamples.card.subheading);
    const [paragraph, more] = container.querySelectorAll("p");
    expect(paragraph).toHaveTextContent(m.templateSamples.card.paragraph);
    expect(more).toHaveTextContent(m.templateSamples.card.more);
    // The look is the template's, unchanged by the language.
    expect(heading.style.fontFamily).toBe("Georgia, serif");
    expect(heading.style.fontSize).toBe("20pt");
    expect(paragraph.style.textAlign).toBe("justify");
    expect(paragraph.style.lineHeight).toBe("1.5");
    expect((container.querySelector(".ProseMirror") as HTMLElement).style.zoom).toBe("0.42");
  });

  it("English cards hold no Bulgarian", () => {
    const { container } = inLanguage("en", <TemplatePreviewSample styles={STYLES} />);
    expect(container.textContent).not.toMatch(CYRILLIC);
  });
});

describe("StylePreviewPage (the template's sample page)", () => {
  it("in English: English sample words; the template's header and footer exactly as the template has them", () => {
    inLanguage("en", <StylePreviewPage preview={PREVIEW} stale={false} />);
    const page = screen.getByRole("img", { name: en.templateEditor.preview.label });
    expect(page).toHaveTextContent("1. Introduction");
    expect(page).toHaveTextContent("Number of pages");
    expect(page).toHaveTextContent('print("Hello")');
    expect(page.querySelectorAll("li")).toHaveLength(3);
    expect(page).toHaveTextContent("Годишен отчет"); // the header is the template's own words: never translated
    expect(page).toHaveTextContent("Фирма ООД");
    const sampleText = page.querySelector(".ProseMirror")!.textContent ?? "";
    expect(sampleText).not.toMatch(CYRILLIC);
    expect((page.querySelector("h1") as HTMLElement).style.fontFamily).toBe("Georgia, serif");
  });

  it("in Bulgarian: the Bulgarian sample page, as before", () => {
    inLanguage("bg", <StylePreviewPage preview={PREVIEW} stale={false} />);
    const page = screen.getByRole("img", { name: bg.templateEditor.preview.label });
    expect(page).toHaveTextContent("1. Въведение");
    expect(page).toHaveTextContent("Брой страници");
    expect(page).toHaveTextContent('print("Здравей")');
    expect(page).toHaveTextContent("Годишен отчет");
  });
});

describe("the sample words (S2-098)", () => {
  it("every Bulgarian sample has Cyrillic in it -- the cards still show whether a template's font has Cyrillic -- and no English one does", () => {
    for (const text of strings(bg.templateSamples)) expect(text).toMatch(CYRILLIC);
    for (const text of strings(en.templateSamples)) expect(text).not.toMatch(CYRILLIC);
  });
});
