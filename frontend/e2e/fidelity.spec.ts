import path from "node:path";

import { expect, test } from "@playwright/test";

import { createDocument, GOLDEN, openPanel, signUp } from "./helpers";

/**
 * The import report (tracker FID-004): after uploading a Word file the editor
 * says whether every word of it made it in -- only because the words were
 * compared -- and the Проверка panel lists what was changed or left out.
 */
test("an uploaded Word file shows its content check and what the import noted", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { file: path.join(GOLDEN, "12-complex.docx") });

  await expect(page.getByTitle(/From the import check/)).toContainText("No content changes");

  await openPanel(page, "Проверка");
  await expect(page.getByText(/All \d+ words of the Word file are in the document, in the same order\./)).toBeVisible();
});
