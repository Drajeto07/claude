import { expect, test } from "@playwright/test";

import { createDocument, editor, openPanel, signUp } from "./helpers";

/**
 * An instruction that would change the text never does so by itself (brief §19,
 * tracker AI-005..AI-007): its formatting applies, its deletion waits in
 * "Changes to review" -- accepted, the paragraph goes (and stays gone after a
 * reload); rejected, it stays. The end-to-end server's AI (backend
 * scripts/e2e_ai.py) answers these instructions as the real model would.
 */
test("an instruction's deletion waits for review: accepted it goes, rejected it stays", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { text: "# Report\n\nKeep this paragraph.\n\nDrop this paragraph." });

  await openPanel(page, "Инструкции");
  await page.getByLabel("Instructions").fill("make the title red and delete “Drop this”");
  await page.getByRole("button", { name: "Apply instructions" }).click();

  await expect(page.getByText(/Applied 1 change from your instructions\. 1 change to the text waits for your review/)).toBeVisible();
  await expect(editor(page).getByRole("heading", { name: "Report" })).toHaveCSS("color", "rgb(255, 0, 0)"); // formatting: applied
  await expect(editor(page).getByText("Drop this paragraph.")).toBeVisible(); // the text: untouched
  await expect(page.getByText("1 AI change to review")).toBeVisible();
  const review = page.getByRole("region", { name: "Changes to review" });
  await expect(review.getByText("Drop this paragraph.")).toBeVisible();

  await review.getByRole("button", { name: "Accept" }).click();
  await expect(editor(page).getByText("Drop this paragraph.")).toHaveCount(0);
  await expect(page.getByText("1 AI change to review")).toHaveCount(0);
  await page.reload();
  await expect(editor(page).getByText("Keep this paragraph.")).toBeVisible();
  await expect(editor(page).getByText("Drop this paragraph.")).toHaveCount(0);

  await openPanel(page, "Инструкции");
  await page.getByLabel("Instructions").fill("delete “Keep this”");
  await page.getByRole("button", { name: "Apply instructions" }).click();
  await expect(page.getByText(/1 change to the text waits for your review/)).toBeVisible();
  await page.getByRole("region", { name: "Changes to review" }).getByRole("button", { name: "Reject" }).click();
  await expect(page.getByRole("region", { name: "Changes to review" })).toHaveCount(0);
  await page.reload();
  await expect(editor(page).getByText("Keep this paragraph.")).toBeVisible();
});
