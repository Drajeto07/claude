import path from "node:path";

import { expect, test } from "@playwright/test";

import { createDocument, editor, signUp } from "./helpers";

/**
 * A Word text box is a box on the page here (tracker DOCX-019A), holding its own paragraphs
 * -- not paragraphs of the document's own -- and stays one after a save and a reload.
 */
const A09 = path.resolve(__dirname, "..", "..", "backend", "tests", "fixtures", "word", "a09-objects.docx");

test("a Word text box is a box holding its own text", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { file: A09 });
  const box = editor(page).locator('div[data-type="text-box"]').first();
  await expect(box).toContainText("Text inside a text box");
  await expect(box).toHaveCSS("border-top-style", "solid");
  await expect(editor(page).locator('div[data-type="text-box"]')).toHaveCount(2);

  await box.getByText("Text inside a text box").click();
  await page.keyboard.press("End");
  await page.keyboard.type(" -- edited");
  await expect(page.getByText("Saved")).toBeVisible({ timeout: 15_000 });
  await page.reload();
  await expect(editor(page).locator('div[data-type="text-box"]').first()).toContainText("Text inside a text box -- edited");
});
