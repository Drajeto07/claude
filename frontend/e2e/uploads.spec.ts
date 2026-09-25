import path from "node:path";

import { expect, test } from "@playwright/test";

import { GOLDEN, createDocument, editor, signUp } from "./helpers";

test.beforeEach(async ({ page }) => {
  await signUp(page);
});

test("upload a Word document with a link", async ({ page }) => {
  await createDocument(page, { file: path.join(GOLDEN, "05-links.docx") });

  await expect(editor(page).locator('a[href="https://example.com/docs"]')).toHaveText("the documentation");
  await expect(editor(page).locator('a[href="mailto:team@example.org"]')).toHaveText("write to us");
});

test("upload a Word document with pictures", async ({ page }) => {
  await createDocument(page, { file: path.join(GOLDEN, "04-images.docx") });

  const pictures = editor(page).locator("img");
  await expect(pictures).toHaveCount(2);
  // Stored as assets on upload and served back by the API, not kept inline.
  await expect(pictures.first()).toHaveAttribute("src", /\/api\/assets\//);
  await expect.poll(() => pictures.first().evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
});

test("upload a Word document with captions", async ({ page }) => {
  await createDocument(page, { file: path.join(GOLDEN, "08-caption.docx") });

  await expect(editor(page).locator('p[data-caption="true"]')).toHaveText(["Figure 1: The blue box.", "Table 1. Quarterly prices"]);
});

test("upload a Word document with everything, formatted with a template", async ({ page }) => {
  await createDocument(page, { file: path.join(GOLDEN, "12-complex.docx") }, { template: "Академичен" });

  const text = editor(page);
  await expect(text.getByRole("heading", { name: "Проектен отчет" })).toBeVisible();
  await expect(text.locator('a[href="https://example.com/report"]')).toHaveText("link");
  await expect(text.getByRole("cell", { name: "Ink, all quarters" })).toBeVisible();
  await expect(text.locator("blockquote")).toContainText("Quality is never an accident.");
  await expect(text.locator("pre")).toContainText("total = sum(prices)");
  await expect(text.locator('p[data-caption="true"]')).toHaveText(["Table 1. Prices", "Figure 1: A purple square."]);
  await expect(text.locator('p[data-footnote="true"]')).toContainText("Sources are listed at the end.");
  await expect(text.getByText("Всички цели са изпълнени навреме.")).toHaveCSS("font-family", /Times New Roman/);
});
