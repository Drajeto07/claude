import path from "node:path";

import { expect, test } from "@playwright/test";

import { API, createDocument, editor, GOLDEN, signUp } from "./helpers";

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

test("a table text flows around floats at its side, with the text beside it, and keeps floating after a reload", async ({ page }) => {
  // DOCX-017B: floating tables used to be shown in line.
  await signUp(page);
  const id = await createDocument(page, { text: "Before the table." });
  const cell = (text: string) => ({ inline: [{ text, marks: [] }] });
  const beside = "Text beside the table. ".repeat(12).trim();
  const table = {
    type: "table",
    content: "Item | Price\nTea | 2",
    order: 1,
    table: {
      rows: [{ cells: [cell("Item"), cell("Price")] }, { cells: [cell("Tea"), cell("2")] }],
      columnWidthsCm: [2.5, 2.5],
      hasHeaderRow: false,
      floating: { xAlign: "right", side: "right", leftFromTextCm: 0.5 },
    },
  };
  const paragraph = { type: "paragraph", content: beside, inline: [{ text: beside, marks: [] }], order: 2 };
  const current = await (await page.request.get(`${API}/documents/${id}`)).json();
  const saved = await page.request.put(`${API}/documents/${id}/content`, { data: { elements: [current.elements[0], table, paragraph] } });
  expect(saved.ok(), await saved.text()).toBeTruthy();
  await page.reload();

  const wrapper = editor(page).locator(".tableWrapper").first();
  await expect(wrapper).toHaveCSS("align-self", "flex-end");
  await expect
    .poll(async () => {
      const box = (await wrapper.boundingBox())!;
      const line = await editor(page)
        .getByText(beside)
        .evaluate((element) => {
          const range = document.createRange();
          range.selectNodeContents(element);
          const first = range.getClientRects()[0];
          return { right: first.x + first.width, y: first.y };
        });
      return {
        leftOfIt: line.right < box.x + 1, // its lines end before the table ...
        levelWithIt: line.y < box.y + box.height, // ... beside it, not below
      };
    })
    .toEqual({ leftOfIt: true, levelWithIt: true });
  const stored = await (await page.request.get(`${API}/documents/${id}`)).json();
  expect(stored.elements.find((element: { type: string }) => element.type === "table").table.floating.side).toBe("right");
});
