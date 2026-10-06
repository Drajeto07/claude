import path from "node:path";

import { expect, test } from "@playwright/test";

import { createDocument, editor, isContentSave, signUp } from "./helpers";

/**
 * The brief's workflows (section 79) that no other spec covers yet (TEST-040; the map is in
 * docs/testing/README.md): formatting by hand, a link typed in the editor, a table added from
 * the editor's menu, and a PDF imported and edited. Each saves and survives a reload.
 */

const PDF = path.resolve(__dirname, "..", "..", "backend", "tests", "fixtures", "pdf", "text.pdf");

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

  // Today a PDF page imports as its text, one paragraph a page; the structure comes with P2E-002.
  await expect(editor(page).getByText(/Quarterly report .*A second paragraph is set in Times Roman\./)).toBeVisible();
  const paragraph = editor(page).getByText(/^Details The second page holds the details\./);
  await paragraph.click();
  await page.keyboard.press("End");
  const saved = page.waitForResponse(isContentSave);
  await page.keyboard.type(" Edited here.");
  await saved;
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();

  await page.reload();
  await expect(editor(page).getByText(/plain as well\. Edited here\./)).toBeVisible();
});
