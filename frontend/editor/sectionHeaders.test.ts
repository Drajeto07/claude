import { describe, expect, it } from "vitest";

import type { Document, Element } from "@/types/document";

import { formatPageNumber, pageChrome, type SectionSettings } from "./sectionHeaders";

/**
 * Each page's header, footer and number in the editor, as Word shows them (tracker
 * DOCX-015, brief §24): the section a page is in gives them -- its own, or the
 * previous section's where it has none of that kind -- and never the last section's
 * on every page.
 */

function section(overrides: Partial<SectionSettings>): SectionSettings {
  return {
    start: "nextPage",
    orientation: null,
    pageWidthMm: null,
    pageHeightMm: null,
    marginTopCm: null,
    marginBottomCm: null,
    marginLeftCm: null,
    marginRightCm: null,
    headerDistanceCm: null,
    footerDistanceCm: null,
    columns: null,
    columnSpacingCm: null,
    pageNumberStart: null,
    pageNumberFormat: null,
    header: null,
    footer: null,
    firstHeader: null,
    firstFooter: null,
    evenHeader: null,
    evenFooter: null,
    differentFirstPage: null,
    ...overrides,
  };
}

function withSections(
  breaks: SectionSettings[],
  last: { header?: string | null; footer?: string | null; lastSection?: SectionSettings | null; evenAndOddHeaders?: boolean } = {},
): Document {
  const elements = breaks.map((settings, index) => ({ id: `b${index}`, type: "section_break", sectionBreak: settings }) as unknown as Element);
  return {
    elements,
    settings: { header: last.header ?? null, footer: last.footer ?? null },
    lastSection: last.lastSection ?? null,
    evenAndOddHeaders: last.evenAndOddHeaders ?? false,
  } as unknown as Document;
}

describe("page headers and footers by section", () => {
  it("shows each section its own header, a cover its own empty one, and numbers as the section says", () => {
    const document = withSections(
      [section({ header: "Front matter", firstHeader: "", differentFirstPage: true, footer: "Page {PAGE}", pageNumberFormat: "lowerRoman" })],
      { header: "Chapter one", lastSection: section({ pageNumberStart: 1 }) },
    );

    const pages = pageChrome(document, [0, 0, 1, 1]);

    expect(pages.map((page) => page.header)).toEqual(["", "Front matter", "Chapter one", "Chapter one"]);
    // The cover has no first-page footer of its own: none, as in Word; the last section's is linked.
    expect(pages.map((page) => page.footer)).toEqual([null, "Page {PAGE}", "Page {PAGE}", "Page {PAGE}"]);
    expect(pages.map((page) => page.label)).toEqual(["i", "ii", "1", "2"]);
  });

  it("shows the previous section's header where a section has none of its own, and none where its own is empty", () => {
    const breaks = [section({ header: "Chapter one" })];

    expect(pageChrome(withSections(breaks), [0, 1]).map((page) => page.header)).toEqual(["Chapter one", "Chapter one"]);
    expect(pageChrome(withSections(breaks, { lastSection: section({ header: "" }) }), [0, 1]).map((page) => page.header)).toEqual([
      "Chapter one",
      "",
    ]);
    expect(pageChrome(withSections(breaks, { header: "Chapter two" }), [0, 1]).map((page) => page.header)).toEqual([
      "Chapter one",
      "Chapter two",
    ]);
  });

  it("shows even-numbered pages their even headers when the document has them, by the number they show", () => {
    const breaks = [section({ header: "Odd", evenHeader: "Even" })];
    const document = withSections(breaks, { evenAndOddHeaders: true, lastSection: section({ pageNumberStart: 1 }) });

    const pages = pageChrome(document, [0, 0, 0, 1, 1]);

    expect(pages.map((page) => page.label)).toEqual(["1", "2", "3", "1", "2"]);
    expect(pages.map((page) => page.header)).toEqual(["Odd", "Even", "Odd", "Odd", "Even"]); // linked, both kinds
    expect(pageChrome(withSections(breaks), [0, 0]).map((page) => page.header)).toEqual(["Odd", "Odd"]); // no even pages of their own
  });

  it("gives a section's first page its first-page header only when the section has one", () => {
    const breaks = [section({ header: "Main", firstHeader: "First", differentFirstPage: true }), section({ differentFirstPage: true })];

    const pages = pageChrome(withSections(breaks), [0, 0, 1, 1, 2]);

    // The second section's first page links to the first section's first-page header; the last has no first page of its own.
    expect(pages.map((page) => page.header)).toEqual(["First", "Main", "First", "Main", "Main"]);
  });

  it("counts page numbers as Word does", () => {
    expect([1, 26, 27, 28, 53].map((value) => formatPageNumber(value, "lowerLetter"))).toEqual(["a", "z", "aa", "bb", "aaa"]);
    expect([formatPageNumber(28, "upperLetter"), formatPageNumber(1994, "lowerRoman"), formatPageNumber(4, "upperRoman")]).toEqual(["BB", "mcmxciv", "IV"]);
    expect([formatPageNumber(0, "lowerRoman"), formatPageNumber(4000, "upperRoman"), formatPageNumber(7, "decimal"), formatPageNumber(7, null)]).toEqual([
      "0",
      "4000",
      "7",
      "7",
    ]);
  });
});
