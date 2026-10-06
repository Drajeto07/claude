import { expect, test } from "@playwright/test";

import { createDocument, editor, openPanel, signUp } from "./helpers";

/**
 * Translation (tracker TRAN-008, brief §51, §94): a block translated as a proposal, shown
 * original against translation and applied only when accepted; a whole document translated
 * as a new version beside the original. The E2E server translates with the pseudo-translation
 * (TRANSLATION_PROVIDER=pseudo): letters changed, everything a translation must keep kept.
 */

test.beforeEach(async ({ page }) => {
  await signUp(page);
});

test("a paragraph is translated as a proposal, with its bold, and changes only when accepted", async ({ page }) => {
  await createDocument(page, { text: "# Dosage guide\n\nTake **5 mg** of the medicine every morning." });
  await editor(page).getByText("of the medicine every morning.").click();
  await openPanel(page, "Превод");
  await expect(page.getByRole("note")).toContainText("AI-assisted translation — review required.");

  await page.getByLabel("Translate into").selectOption("bg");
  await page.getByRole("button", { name: "Translate selection" }).click();
  await expect(page.getByText("1 block translated into Bulgarian: review below.")).toBeVisible();
  const review = page.getByRole("region", { name: "Changes to review" });
  await expect(review).toContainText("Translate a block into Bulgarian");
  await expect(review).toContainText("Táké 5 mg óf thé médíçíñé évérý mórñíñg.");
  await expect(editor(page).getByText("of the medicine every morning.")).toBeVisible(); // nothing changed yet

  await review.getByRole("button", { name: "Accept" }).click();
  await expect(editor(page).getByText("óf thé médíçíñé évérý mórñíñg.")).toBeVisible();
  await expect(editor(page).locator("strong")).toHaveText("5 mg"); // its bold where its words went
});

test("a whole document becomes a translated version, and the original stays as it was", async ({ page }) => {
  const original = await createDocument(page, { text: "# Dosage guide\n\nKeep the tablets dry." });
  await openPanel(page, "Превод");
  await page.getByLabel("Translate into").selectOption("de");
  await page.getByRole("button", { name: "Create translated version" }).click();

  await page.waitForURL((url) => /\/documents\/[0-9a-f-]{36}$/.test(url.pathname) && !url.pathname.endsWith(original));
  await expect(editor(page).getByText("Kéép thé táblétš drý.")).toBeVisible();
  await expect(page.getByText("Dosage guide (German)")).toBeVisible();

  await page.goto(`/documents/${original}`);
  await expect(editor(page).getByText("Keep the tablets dry.")).toBeVisible();
});
