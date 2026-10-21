import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { templateText } from "@/components/templates/templateText";
import { bg } from "@/i18n/messages/bg";
import { en } from "@/i18n/messages/en";

/** The built-in templates as the server has them (its words are Bulgarian). */
const SERVER: { id: string; name: string; description: string }[] = JSON.parse(
  readFileSync(path.resolve(__dirname, "..", "..", "..", "backend", "app", "formatting", "builtin_templates.json"), "utf-8"),
);

const academic = SERVER.find((each) => each.id === "academic-default")!;

describe("templateText (S2-028)", () => {
  it("names and describes a built-in template in the interface's language", () => {
    const template = { ...academic, builtin: true };
    expect(templateText(template, en)).toEqual({
      name: "Academic",
      description: "Coursework / essay / thesis -- Times New Roman, 1.5 line spacing, justified paragraphs.",
    });
    expect(templateText(template, bg)).toEqual({ name: academic.name, description: academic.description });
  });

  it("leaves a template of the user's own as it was saved, in either language", () => {
    // Made by the user, duplicated from a built-in, or imported from Word: never translated.
    const own = [
      { id: "8f6c0d0e-0000-4000-8000-000000000001", builtin: false, name: "Моят шаблон", description: "Само за мен." },
      { id: "8f6c0d0e-0000-4000-8000-000000000002", builtin: false, name: "Академичен (copy)", description: academic.description },
      { id: "8f6c0d0e-0000-4000-8000-000000000003", builtin: false, name: "Отчет", description: "The look of отчет.docx." },
      // Not built-in, even with a built-in's id: kept.
      { id: "academic-default", builtin: false, name: "Something else", description: "" },
    ];
    for (const template of own) {
      for (const m of [en, bg]) expect(templateText(template, m)).toEqual({ name: template.name, description: template.description });
    }
  });

  it("keeps the server's words for a built-in the dictionaries don't know yet", () => {
    const later = { id: "future-builtin", builtin: true, name: "Нов шаблон", description: "Описание." };
    expect(templateText(later, en)).toEqual({ name: "Нов шаблон", description: "Описание." });
  });

  it("covers exactly the server's built-in templates, and the Bulgarian is the server's own wording", () => {
    const ids = SERVER.map((each) => each.id).sort();
    expect(Object.keys(en.templatesPage.builtins).sort()).toEqual(ids);
    expect(Object.keys(bg.templatesPage.builtins).sort()).toEqual(ids);
    for (const { id, name, description } of SERVER) {
      expect(bg.templatesPage.builtins[id as keyof typeof bg.templatesPage.builtins]).toEqual({ name, description });
      const english = en.templatesPage.builtins[id as keyof typeof en.templatesPage.builtins];
      expect(english.name).not.toBe(name);
      expect(english.name + english.description).not.toMatch(/[Ѐ-ӿ]/); // no Cyrillic left in English
    }
  });
});
