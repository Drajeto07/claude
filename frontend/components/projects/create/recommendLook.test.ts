import { describe, expect, it } from "vitest";

import type { Element, Template } from "@/types/document";

import { suggestCategory, suggestLook } from "./recommendLook";

let order = 0;
const heading = (text: string, level = 1) => ({ id: `h${order}`, type: "heading", level, content: text, order: order++ }) as Element;
const para = (text: string) => ({ id: `p${order}`, type: "paragraph", content: text, order: order++ }) as Element;
const block = (type: Element["type"]) => ({ id: `b${order}`, type, content: "", order: order++ }) as Element;

const templates = [
  { id: "academic-default", category: "academic", builtin: true },
  { id: "professional-cv", category: "professional", builtin: true },
  { id: "official-standard", category: "official", builtin: true },
  { id: "modern-report", category: "business", builtin: true },
  { id: "legal-contract", category: "legal", builtin: true },
] as Template[];

describe("the suggested look (M3.3, built-in rules)", () => {
  it("a CV: its section names point to the professional CV template", () => {
    const cv = [heading("Мария Иванова"), heading("Професионален опит", 2), para("Дизайнер, 2020–2026."), heading("Образование", 2), para("СУ."), heading("Умения", 2)];
    expect(suggestLook(cv, "CV", templates)).toMatchObject({ templateId: "professional-cv", category: "professional" });
  });

  it("a contract in English", () => {
    const contract = [heading("Service agreement"), para("The parties agree as follows."), heading("1. Clause on payment", 2)];
    expect(suggestCategory(contract)?.category).toBe("legal");
  });

  it("a report with tables: business, and the tables are part of the reason", () => {
    const report = [heading("Годишен отчет 2026"), para("Приходите растат."), block("table"), heading("Анализ на пазара", 2)];
    const found = suggestCategory(report);
    expect(found?.category).toBe("business");
    expect(found?.evidence).toEqual(expect.arrayContaining([{ kind: "tables", count: 1 }]));
  });

  it("a coursework paper: academic, with the words it found", () => {
    const paper = [heading("Курсова работа"), heading("Въведение", 2), para("..."), heading("Методология", 2), heading("Заключение", 2), heading("Използвана литература", 2)];
    const found = suggestCategory(paper);
    expect(found?.category).toBe("academic");
    expect(found?.evidence[0]).toMatchObject({ kind: "words" });
  });

  it("an application letter: official", () => {
    expect(suggestCategory([heading("Молба"), para("Уважаеми господин Директор, ... С уважение,")])?.category).toBe("official");
  });

  it("nothing clear: no suggestion rather than a guess", () => {
    expect(suggestCategory([heading("Wedding menu"), para("Shopska salad. Honey cake.")])).toBeNull();
  });

  it("words only count where a word starts", () => {
    expect(suggestCategory([para("abcv xcontract preport")])).toBeNull();
  });

  it("no template of that kind: no suggestion", () => {
    const cv = [heading("CV"), heading("Work experience", 2), heading("Education", 2)];
    expect(suggestLook(cv, "", templates.filter((template) => template.category !== "professional"))).toBeNull();
  });
});
