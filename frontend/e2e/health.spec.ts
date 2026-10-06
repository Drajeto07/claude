import { expect, test } from "@playwright/test";

import { createDocument, editor, openPanel, signUp } from "./helpers";

/**
 * Document Health fixes (tracker HLTH-002): a check's fix is proposed, shown with what it
 * changes, and changes nothing until accepted -- then the heading takes its new level, and
 * stays so after a reload. Worked out by rules: no AI is involved.
 */
test("a health fix waits for review and applies when accepted", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { text: "# Report\n\nThe opening paragraph.\n\n### Details\n\nMore text about it.\n\n\n\n" });
  await expect(editor(page).locator("h3", { hasText: "Details" })).toBeVisible();

  await openPanel(page, "Здраве");
  await page.getByRole("button", { name: "Propose fixes: Structure" }).click();
  const review = page.getByRole("region", { name: "Changes to review" });
  await expect(review.getByText(/Heading 3 → Heading 2/)).toBeVisible();
  await expect(page.getByText("1 fix to review")).toBeVisible();
  await expect(page.getByText(/AI changes? to review/)).toHaveCount(0);
  await expect(editor(page).locator("h3", { hasText: "Details" })).toBeVisible(); // nothing changed yet

  await review.getByRole("button", { name: "Accept" }).click();
  await expect(editor(page).locator("h2", { hasText: "Details" })).toBeVisible();
  await expect(page.getByText("1 fix to review")).toHaveCount(0);
  await page.reload();
  await expect(editor(page).locator("h2", { hasText: "Details" })).toBeVisible();
});
