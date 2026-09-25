import path from "node:path";

import { expect, test } from "@playwright/test";

import { GOLDEN, createDocument, editor, openPanel, signUp } from "./helpers";

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
  await expect(body).not.toHaveCSS("font-family", /Calibri/);

  await openPanel(page, "Шаблони");
  await page.getByLabel("Reference Word document").setInputFiles(path.join(GOLDEN, "12-complex.docx"));
  await expect(page.getByText(/The look of/)).toBeVisible();
  await page.getByRole("button", { name: "Apply to this document" }).click();

  // The reference's body text is Calibri, so this document's is now too.
  await expect(body).toHaveCSS("font-family", /Calibri/);
});
