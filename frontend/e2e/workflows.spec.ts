import path from "node:path";

import { expect, test } from "@playwright/test";

import { createDocument, editor, isContentSave, openPanel, signUp } from "./helpers";

/**
 * The brief's workflows (section 79) that no other spec covers yet (TEST-040; the map is in
 * docs/testing/README.md): formatting by hand, a link typed in the editor, a table added from
 * the editor's menu, and a PDF imported and edited. Each saves and survives a reload.
 */

const PDF = path.resolve(__dirname, "..", "..", "backend", "tests", "fixtures", "pdf", "text.pdf");
const STRUCTURE_PDF = path.resolve(__dirname, "..", "..", "backend", "tests", "fixtures", "pdf", "structure.pdf");

test.beforeEach(async ({ page }) => {
  await signUp(page);
});

test("manual edit: a word made bold from the toolbar stays bold after a reload", async ({ page }) => {
  await createDocument(page, { text: "# Notes\n\nA plain sentence to emphasise." });

  await editor(page).getByText("A plain sentence to emphasise.").dblclick({ position: { x: 20, y: 5 } });
  const saved = page.waitForResponse(isContentSave);
  await page.getByRole("button", { name: "Bold", exact: true }).first().click(); // the toolbar's (the Properties panel has one too)
  await saved;
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();

  await page.reload();
  await expect(editor(page).locator("strong")).toHaveCount(1);
  await expect(editor(page).locator("strong")).toHaveText("plain"); // the word double-clicked (with the space after it, as browsers select), not the sentence
});

test("hyperlink: an address typed in the editor becomes a link and stays one", async ({ page }) => {
  await createDocument(page, { text: "# Links\n\nThe guide lives here:" });

  await editor(page).getByText("The guide lives here:").click();
  await page.keyboard.press("End");
  const saved = page.waitForResponse((response) => isContentSave(response) && (response.request().postData() ?? "").includes("example.com/guide"));
  await page.keyboard.type(" https://example.com/guide and more.");
  await saved;
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();

  await page.reload();
  await expect(editor(page).locator('a[href="https://example.com/guide"]')).toHaveText("https://example.com/guide");
});

test("tables: a table added from the editor's menu is kept", async ({ page }) => {
  await createDocument(page, { text: "# Plan\n\nThe table goes after this paragraph." });

  await editor(page).getByText("The table goes after this paragraph.").click();
  await page.getByRole("button", { name: "Добави елемент" }).click();
  await page.getByRole("button", { name: "Table" }).click();
  await expect(editor(page).locator("table")).toHaveCount(1);

  await page.reload();
  await expect(editor(page).locator("table")).toHaveCount(1);
  await expect(editor(page).getByText("The table goes after this paragraph.")).toBeVisible();
});

test("PDF import: a PDF opens as an editable document, and an edit to it is kept", async ({ page }) => {
  await createDocument(page, { file: PDF });

  // Its structure rebuilt from where its text sits (P2E-002): the title a heading, each paragraph its own.
  await expect(editor(page).locator("h1", { hasText: "Quarterly report" })).toBeVisible();
  await expect(editor(page).locator("h2", { hasText: "Details" })).toBeVisible();
  const paragraph = editor(page).getByText("The second page holds the details. Its words are plain as well.");
  await paragraph.click();
  await page.keyboard.press("End");
  const saved = page.waitForResponse(isContentSave);
  await page.keyboard.type(" Edited here.");
  await saved;
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();

  await page.reload();
  await expect(editor(page).getByText(/plain as well\. Edited here\./)).toBeVisible();
});

test("PDF import, layout-focused: its pages are kept, and the conversion says how sure it is", async ({ page }) => {
  await createDocument(page, { file: STRUCTURE_PDF }, { layout: true });

  // A page break where each of its three pages began; the running header became the document's.
  await expect(editor(page).locator('[data-page-break="true"]')).toHaveCount(2);
  await expect(editor(page).locator("h1", { hasText: "Annual review" })).toBeVisible();
  await expect(editor(page).locator("ul ul").getByText("Travel ran over.", { exact: true })).toBeVisible(); // a nested item

  await openPanel(page, "Проверка");
  const conversion = page.getByRole("region", { name: "PDF conversion" });
  await expect(conversion).toContainText("Imported from PDF · layout-focused");
  await expect(conversion).toContainText("Conversion confidence");
});

