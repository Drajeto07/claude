import path from "node:path";

import { expect, test } from "@playwright/test";

import { createDocument, editor, GOLDEN, signUp } from "./helpers";

/**
 * A Word file's lists show their own labels on the pages, as Word numbers them
 * (tracker DOCX-016, brief §25): labels of their own, 1.1-style numbers five levels
 * deep, Cyrillic letters, a list Word restarts, one going on after a section break.
 */

test("each list item shows the label Word gives it", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { file: path.join(GOLDEN, "15-numbering.docx") });

  // The item the text is in: its nearest list item.
  const label = (text: string) => editor(page).getByText(text, { exact: true }).first().locator("xpath=ancestor::li[1]");
  await expect(label("Apples")).toHaveAttribute("data-label", "1)");
  await expect(label("Fruit")).toHaveAttribute("data-label", "A.");
  await expect(label("Defined terms")).toHaveAttribute("data-label", "1.1.1.");
  await expect(label("Level 5")).toHaveAttribute("data-label", "1.1.1.1.1.");
  await expect(label("Предмет")).toHaveAttribute("data-label", "Чл. 1.");
  await expect(label("втора точка")).toHaveAttribute("data-label", "б)");
  await expect(label("Срок")).toHaveAttribute("data-label", "Чл. 2.");
  await expect(label("First again")).toHaveAttribute("data-label", "1)"); // Word restarts it
  await expect(label("After the break")).toHaveAttribute("data-label", "03."); // it goes on after the section break
  // The label is drawn on the page, just before the item's text.
  const content = await label("Предмет").evaluate((item) => getComputedStyle(item, "::before").content);
  expect(content).toContain("Чл. 1.");
});
