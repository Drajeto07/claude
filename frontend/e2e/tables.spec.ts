import path from "node:path";

import { expect, test } from "@playwright/test";

import { createDocument, editor, GOLDEN, signUp } from "./helpers";

/**
 * A Word file's tables on the pages, as Word lays them out (tracker DOCX-017, brief
 * §26): their own column widths and borders, a cell's own border and alignment, and
 * a cell that holds paragraphs, a list and a table of its own.
 */

test("tables keep their widths, borders and what their cells hold", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { file: path.join(GOLDEN, "16-table-engine.docx") });

  const tables = editor(page).locator(".tableWrapper.word-table");
  await expect(tables.first()).toBeVisible();
  const widths = await tables.first().locator("col").evaluateAll((cols) => cols.map((col) => (col as HTMLElement).style.width));
  expect(widths).toEqual(["189px", "113px", "113px"]); // 5, 3 and 3 cm
  const cellOf = (text: string) => editor(page).getByText(text, { exact: true }).locator("xpath=ancestor::td[1]");
  expect(await cellOf("12.50").evaluate((cell) => getComputedStyle(cell).verticalAlign)).toBe("middle");
  // Its own double bottom border: the edge it shares with the cell below, drawn once.
  expect(await cellOf("3.20").evaluate((cell) => getComputedStyle(cell).borderTopStyle)).toBe("double");

  // The busy cell: its list numbered, its own table inside it.
  const apples = editor(page).getByText("apples", { exact: true }).locator("xpath=ancestor::li[1]");
  await expect(apples).toHaveAttribute("data-label", "•");
  await expect(editor(page).locator("td table td", { hasText: "and a table" })).toBeVisible();
});
