import { expect, test } from "@playwright/test";

import { API, createDocument, editor, openPanel, signUp } from "./helpers";

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

/**
 * Repair document (tracker REV-004): a table with a row short of its width is found in the
 * Преглед panel's repair list; its fix is proposed, shown with the table as it would be, and
 * applied only once accepted.
 */
test("a broken table is repaired once its fix is accepted", async ({ page }) => {
  await signUp(page);
  const id = await createDocument(page, { text: "A paragraph before the table." });
  const cell = (text: string) => ({ inline: text ? [{ text, marks: [] }] : [] });
  const table = {
    type: "table",
    content: "Name | Qty | Price\nTea | 2",
    order: 1,
    table: { rows: [{ cells: [cell("Name"), cell("Qty"), cell("Price")] }, { cells: [cell("Tea"), cell("2")] }] },
  };
  const current = await (await page.request.get(`${API}/documents/${id}`)).json();
  const saved = await page.request.put(`${API}/documents/${id}/content`, { data: { elements: [current.elements[0], table] } });
  expect(saved.ok(), await saved.text()).toBeTruthy();
  await page.reload();

  await openPanel(page, "Преглед");
  const repair = page.getByRole("region", { name: "Repair document" });
  await expect(repair.getByText("Tables")).toBeVisible();
  await repair.getByRole("button", { name: "Propose repairs: Table structure" }).click();
  const structure = page.getByRole("region", { name: "Structure changes" });
  await expect(structure.getByText(/Repair a table/)).toBeVisible();
  // The stored table, as the server has it (the editor draws a short row padded already).
  const secondRow = async () => {
    const stored = await (await page.request.get(`${API}/documents/${id}`)).json();
    return stored.elements.find((element: { type: string }) => element.type === "table").table.rows[1].cells.length;
  };
  expect(await secondRow()).toBe(2); // nothing applied yet

  await structure.getByRole("button", { name: "Accept" }).click();
  await expect.poll(secondRow).toBe(3);
  await expect(repair).toHaveCount(0); // nothing left to repair
});
