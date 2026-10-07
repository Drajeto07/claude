import { formatListNumber } from "@/editor/listLabels";
import type { Document, Element } from "@/types/document";

/**
 * Each page's header, footer and page number, as Word shows them (tracker DOCX-015,
 * brief §24: the last section's header is not the whole document's). A page is in
 * the section it begins in -- editor/pagination.ts says which each page is in: a
 * continuous section's pages start with the page after the one it starts on, and a
 * blank page before an even or odd start is the section before's. Its header and
 * footer are its section's own -- the first-page ones on the section's first page
 * when it has them, the even-page ones on even-numbered pages when the document has
 * them -- or, where it has none of that kind, the previous section's ("link to
 * previous"). Its number runs on from the page before, or restarts where its section
 * says. The same rules as the PDF's (backend export/pdf_export.py _HeaderTexts, _Numbering).
 */

export type SectionSettings = NonNullable<Element["sectionBreak"]>;
export type TextKey = "header" | "footer" | "firstHeader" | "firstFooter" | "evenHeader" | "evenFooter";
/** A page's header, footer and number -- and, so either can be edited as its section's own
 * (DOCX-015C), its section's index and which kind of header and footer the page shows. */
export type PageChrome = { header: string | null; footer: string | null; label: string; section?: number; headerKey?: TextKey; footerKey?: TextKey };

/** Each section's own settings, in order: a section break holds the one it ends; the last is the document's (null). */
export function sectionsOf(document: Pick<Document, "elements">): (SectionSettings | null)[] {
  const breaks = document.elements.filter((element) => element.type === "section_break").map((element) => element.sectionBreak ?? null);
  return [...breaks, null];
}

function own(document: Pick<Document, "settings" | "lastSection">, section: SectionSettings | null, key: TextKey): string | null {
  if (section) return section[key] ?? null;
  // The last section's main ones are the document's; "" in lastSection is one of its own left empty.
  if (key === "header" || key === "footer") return document.settings[key] ?? document.lastSection?.[key] ?? null;
  return document.lastSection?.[key] ?? null;
}

/** A section's text of one kind: its own, or the nearest earlier section's. */
export function textFor(document: Pick<Document, "settings" | "lastSection">, sections: (SectionSettings | null)[], index: number, key: TextKey): string | null {
  for (let at = Math.min(index, sections.length - 1); at >= 0; at -= 1) {
    const text = own(document, sections[at], key);
    if (text !== null) return text;
  }
  return null;
}

/** A page number in its section's style, as Word counts (as a list's: editor/listLabels.ts). */
export const formatPageNumber = formatListNumber;

/** Every page's header, footer and page number, from the section each page is in. */
export function pageChrome(document: Pick<Document, "elements" | "settings" | "lastSection" | "evenAndOddHeaders">, pageSections: number[]): PageChrome[] {
  const sections = sectionsOf(document);
  let number = 0;
  return pageSections.map((sectionIndex, page) => {
    const index = Math.min(sectionIndex, sections.length - 1);
    const settings = sections[index] ?? document.lastSection ?? null;
    const first = page === 0 || pageSections[page - 1] !== sectionIndex;
    number = first && settings?.pageNumberStart != null ? settings.pageNumberStart : number + 1;
    const differentFirst = Boolean(settings?.differentFirstPage);
    const [header, footer]: [TextKey, TextKey] =
      first && differentFirst ? ["firstHeader", "firstFooter"] : number % 2 === 0 && document.evenAndOddHeaders ? ["evenHeader", "evenFooter"] : ["header", "footer"];
    return {
      header: textFor(document, sections, index, header),
      footer: textFor(document, sections, index, footer),
      label: formatPageNumber(number, settings?.pageNumberFormat),
      section: index,
      headerKey: header,
      footerKey: footer,
    };
  });
}

/** Where a page's edited header or footer goes (DOCX-015C): its section's own -- a section break's
 * (`sectionId`), or the last section's (null) -- except the last section's main header and footer,
 * which are the page settings'. */
export type ChromeTarget = { kind: "settings"; property: "header" | "footer" } | { kind: "section"; sectionId: string | null; key: TextKey };

export function chromeTarget(document: Pick<Document, "elements">, chrome: PageChrome | undefined, part: "header" | "footer"): ChromeTarget {
  const breaks = document.elements.filter((element) => element.type === "section_break");
  const index = Math.min(chrome?.section ?? breaks.length, breaks.length);
  const key: TextKey = (part === "header" ? chrome?.headerKey : chrome?.footerKey) ?? part;
  if (index >= breaks.length) return key === part ? { kind: "settings", property: part } : { kind: "section", sectionId: null, key };
  return { kind: "section", sectionId: breaks[index].id, key };
}
