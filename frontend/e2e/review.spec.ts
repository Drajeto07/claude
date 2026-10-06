import { expect, test } from "@playwright/test";

import { createDocument, editor, openPanel, signUp } from "./helpers";

/**
 * Review Changes (tracker REV-002/003): an instruction's deletion and the health check's fixes
 * wait together in the Преглед panel, grouped by what they touch. The structure fixes go in at
 * once with "Accept all"; the deletion -- a change to the words -- has no such button and is
 * accepted on its own. Both stay after a reload.
 */
test("changes from different places are reviewed in one panel, the content's one by one", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { text: "# Report\n\n### First part\n\nKeep this paragraph.\n\n# Annex\n\n### Second part\n\nDrop this paragraph." });

  await openPanel(page, "Инструкции");
  await page.getByLabel("Instructions").fill("delete “Drop this”");
  await page.getByRole("button", { name: "Apply instructions" }).click();
  await expect(page.getByText(/1 change to the text waits for your review/)).toBeVisible();

  await openPanel(page, "Здраве");
  await page.getByRole("button", { name: "Propose fixes: Structure" }).click();
  await expect(page.getByText("2 fixes to review")).toBeVisible();

  await openPanel(page, "Преглед");
  await expect(page.getByText("3 changes to review")).toBeVisible();
  const content = page.getByRole("region", { name: "Content changes" });
  const structure = page.getByRole("region", { name: "Structure changes" });
  await expect(content.getByText("Drop this paragraph.")).toBeVisible();
  await expect(content.getByRole("button", { name: /Accept all/ })).toHaveCount(0);

  await structure.getByRole("button", { name: "Accept all 2" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Accepted 2." })).toBeVisible();
  await expect(editor(page).locator("h2", { hasText: "First part" })).toBeVisible();
  await expect(editor(page).locator("h2", { hasText: "Second part" })).toBeVisible();
  await expect(editor(page).getByText("Drop this paragraph.")).toBeVisible(); // the words: still waiting

  await content.getByRole("button", { name: "Accept" }).click();
  await expect(editor(page).getByText("Drop this paragraph.")).toHaveCount(0);
  await expect(page.getByText(/Nothing waits for review/)).toBeVisible();
  await page.reload();
  await expect(editor(page).locator("h2", { hasText: "Second part" })).toBeVisible();
  await expect(editor(page).getByText("Drop this paragraph.")).toHaveCount(0);
});
