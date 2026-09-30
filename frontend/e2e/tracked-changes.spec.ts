import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { API, createDocument, openPanel, signUp, unzipped } from "./helpers";

/**
 * A Word file's tracked changes (tracker DOCX-022) are shown as if accepted and kept
 * for Word, unless the person chooses to accept them all -- at the review after the
 * upload, or later in the Проверка panel. Never accepted without asking.
 */

const A07 = path.resolve(__dirname, "..", "..", "backend", "tests", "fixtures", "word", "a07-review.docx");

async function insertions(page: Page, id: string): Promise<number> {
  const exported = await page.request.get(`${API}/documents/${id}/export/docx`);
  expect(exported.ok()).toBeTruthy();
  return (unzipped(await exported.body(), "word/document.xml").match(/<w:ins\b/g) ?? []).length;
}

test("a Word file's tracked changes stay for Word unless the person accepts them", async ({ page }) => {
  await signUp(page);
  const id = await createDocument(
    page,
    { file: A07 },
    {
      onReview: async () => {
        await expect(page.getByRole("radio", { name: /Keep them in the Word export/ })).toBeChecked(); // kept unless chosen
        await page.getByRole("radio", { name: /Accept them all/ }).click();
        await expect(page.getByRole("radio", { name: /Accept them all/ })).toBeChecked();
      },
    },
  );
  expect(await insertions(page, id)).toBe(0); // accepted at the review, as chosen

  await openPanel(page, "Проверка");
  await expect(page.getByText(/Tracked changes were accepted, as you chose/)).toBeVisible();
  await page.getByRole("radio", { name: /Keep them in the Word export/ }).click();
  await expect(page.getByText(/A Word export keeps them in the blocks you don't change/)).toBeVisible();

  expect(await insertions(page, id)).toBe(7); // the original file's, as it has them
});
