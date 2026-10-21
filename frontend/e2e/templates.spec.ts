import path from "node:path";

import { expect, test } from "@playwright/test";

import { API, GOLDEN, createDocument, editor, openPanel, signUp } from "./helpers";

test.beforeEach(async ({ page }) => {
  await signUp(page);
});

test("create a template of your own in the library", async ({ page }) => {
  await page.goto("/templates");
  await page.getByRole("button", { name: "New template" }).click();
  await page.waitForURL(/\/templates\/[0-9a-f-]{36}$/);

  await page.getByLabel("Name", { exact: true }).fill("E2E house style");
  await page.getByLabel("Font").first().fill("Georgia");
  await page.getByRole("button", { name: "Save template" }).click();
  await expect(page.getByText(/Saved as version \d+\./)).toBeVisible();

  await page.getByRole("link", { name: "All templates" }).click();
  await expect(page.getByText("E2E house style")).toBeVisible();
});

test("format by example: give a document the look of a Word file", async ({ page }) => {
  await createDocument(page, { text: "# Plan\n\nA paragraph that should take the reference's look." });
  const body = editor(page).getByText("A paragraph that should take the reference's look.");
  // The font it is set in: the stack's first (the rest stand in for it, FONT-005).
  await expect(body).not.toHaveCSS("font-family", /^"?Calibri/);

  await openPanel(page, "Templates");
  await page.getByLabel("Reference Word document").setInputFiles(path.join(GOLDEN, "12-complex.docx"));
  await expect(page.getByText(/The look of/)).toBeVisible();
  await page.getByRole("button", { name: "Apply to this document" }).click();

  // The reference's body text is Calibri, so this document's is now too.
  await expect(body).toHaveCSS("font-family", /^"?Calibri"?, "?Carlito/);
});

test("built-in templates are named in the interface's language; a template of your own keeps its words (S2-028)", async ({ page }) => {
  // One of the user's own, named in Bulgarian: never translated.
  const own = await page.request.post(`${API}/templates`, { data: { name: "Моят стил", description: "Само за мен." } });
  expect(own.ok()).toBe(true);
  const setLanguage = (locale: "en" | "bg") => page.context().addCookies([{ name: "smartdoc_locale", value: locale, url: "http://localhost:3100" }]);

  // The library, in English: the built-ins in English, the user's own as saved.
  await setLanguage("en");
  await page.goto("/templates");
  await expect(page.getByRole("link", { name: "Academic", exact: true })).toBeVisible();
  await expect(page.getByText("Coursework / essay / thesis -- Times New Roman, 1.5 line spacing, justified paragraphs.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Professional (CV)", exact: true })).toBeVisible();
  await expect(page.getByText("Моят стил")).toBeVisible();
  await expect(page.getByText("Само за мен.")).toBeVisible();
  await expect(page.getByText("Академичен")).toHaveCount(0);
  // A built-in's own page: read-only, its name in English.
  await page.getByRole("link", { name: "Academic", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Academic" })).toBeVisible();
  await expect(page.getByLabel("Name", { exact: true })).toHaveValue("Academic");
  await expect(page.getByLabel("Name", { exact: true })).toBeDisabled();

  // The same library in Bulgarian.
  await setLanguage("bg");
  await page.goto("/templates");
  await expect(page.getByRole("link", { name: "Академичен", exact: true })).toBeVisible();
  await expect(page.getByText("Курсова работа / реферат / дипломна работа -- Times New Roman, 1.5 междуредие, обосновани абзаци.")).toBeVisible();
  await expect(page.getByText("Моят стил")).toBeVisible();
  await expect(page.getByText("Academic", { exact: true })).toHaveCount(0);

  // The editor's Templates panel (open beside the pages at this width), in both languages; the same ids underneath.
  const job = await (await page.request.post(`${API}/jobs/import-text`, { data: { text: "# Plan\n\nA paragraph.", title: "Plan" } })).json();
  let id: string | undefined;
  await expect
    .poll(async () => {
      const state = await (await page.request.get(`${API}/jobs/${job.id}`)).json();
      id = state.status === "succeeded" ? state.result?.documentId : undefined;
      return id;
    })
    .toBeTruthy();
  await page.goto(`/documents/${id}`);
  await expect(page.getByRole("button", { name: /^Академичен/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Моят стил/ })).toBeVisible();
  await setLanguage("en");
  await page.reload();
  await expect(page.getByRole("button", { name: /^Academic/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Моят стил/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Академичен/ })).toHaveCount(0);
});

test("template previews speak the interface's language; in Bulgarian their Cyrillic is drawn in the template's own font (S2-098)", async ({ page }) => {
  const templates: { id: string; previewStyles: Record<string, Record<string, string>> }[] = await (await page.request.get(`${API}/templates`)).json();
  const academic = templates.find((template) => template.id === "academic-default")!;
  const setLanguage = (locale: "en" | "bg") => page.context().addCookies([{ name: "smartdoc_locale", value: locale, url: "http://localhost:3100" }]);
  // The first card is the first built-in (a new account has none of its own): Academic.
  const cardHeading = page.locator(".paper h1").first();
  const samplePage = (name: string) => page.getByRole("img", { name });

  await setLanguage("en");
  await page.goto("/templates");
  await expect(cardHeading).toHaveText("Document title");
  await page.getByRole("link", { name: "Academic", exact: true }).click();
  await expect(samplePage("Preview of a page in this template")).toContainText("1. Introduction");
  await expect(samplePage("Preview of a page in this template")).toContainText("Number of pages");

  await setLanguage("bg");
  await page.goto("/templates");
  await expect(cardHeading).toHaveText("Заглавие на документа");
  // The Cyrillic sample is set in the template's heading font, so the card shows whether that font has Cyrillic.
  const font = academic.previewStyles["Heading 1"]["font-family"].replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); // first in the stack the editor draws it with
  await expect(cardHeading).toHaveCSS("font-family", new RegExp(`^"?${font}"?,`));
  await page.getByRole("link", { name: "Академичен", exact: true }).click();
  await expect(samplePage("Преглед на страница в този шаблон")).toContainText("1. Въведение");
});
