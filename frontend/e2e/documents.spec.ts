import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { createDocument, editor, openPanel, signUp } from "./helpers";

const REPORT = "# Quarterly report\n\nRevenue grew in every quarter.\n\n## Costs\n\nCosts stayed flat.";

test.beforeEach(async ({ page }) => {
  await signUp(page);
});

test("create from pasted text and review the structure found", async ({ page }) => {
  await page.goto("/new");
  await page.getByRole("button", { name: /Something else/ }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByPlaceholder("Paste your raw text here...").fill(REPORT);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Decide later" }).click();
  await page.getByRole("button", { name: "Create document" }).click();

  await expect(page.getByRole("heading", { name: "Here’s what we found" })).toBeVisible();
  await expect(page.getByText("2 headings, 2 paragraphs.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Looks good, continue" }).click();

  await expect(editor(page).getByRole("heading", { name: "Quarterly report" })).toBeVisible();
  await expect(editor(page).getByRole("heading", { name: "Costs" })).toBeVisible();
  await expect(editor(page).getByText("Costs stayed flat.")).toBeVisible();
});

test("typing is saved on its own and is still there after a reload", async ({ page }) => {
  await createDocument(page, { text: REPORT });

  await editor(page).getByText("Costs stayed flat.").click();
  await page.keyboard.press("End");
  const saved = page.waitForResponse((response) => response.url().endsWith("/content") && response.request().method() === "PUT" && response.ok());
  await page.keyboard.type(" Next year too.");
  await saved;
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();

  await page.reload();
  await expect(editor(page).getByText("Costs stayed flat. Next year too.")).toBeVisible();
});

test("choose a template, apply it, then undo and redo the formatting", async ({ page }) => {
  await createDocument(page, { text: REPORT });
  const body = editor(page).getByText("Revenue grew in every quarter.");
  await expect(body).not.toHaveCSS("font-family", /Times New Roman/);

  await openPanel(page, "Шаблони");
  await page.getByRole("button", { name: /Академичен/ }).first().click();
  await page.getByRole("button", { name: "Apply formatting" }).click();
  await expect(body).toHaveCSS("font-family", /Times New Roman/);

  await openPanel(page, "Инструкции");
  await page.getByRole("button", { name: "Undo formatting" }).click();
  await expect(body).not.toHaveCSS("font-family", /Times New Roman/);
  await page.getByRole("button", { name: "Redo formatting" }).click();
  await expect(body).toHaveCSS("font-family", /Times New Roman/);
});

test("export to Word and to PDF", async ({ page }) => {
  await createDocument(page, { text: REPORT });

  for (const [format, signature] of [
    ["DOCX", "PK"],
    ["PDF", "%PDF"],
  ] as const) {
    await page.getByRole("button", { name: "Export", exact: true }).click();
    await page.getByRole("button", { name: format, exact: true }).click();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: `Download ${format}` }).click();
    const file = await download;

    expect(file.suggestedFilename()).toBe(`Quarterly report.${format.toLowerCase()}`);
    expect(readFileSync((await file.path())!).subarray(0, signature.length).toString("latin1")).toBe(signature);
  }
});

test("delete a document from the list", async ({ page }) => {
  await createDocument(page, { text: "# To be deleted\n\nSoon gone." });
  await createDocument(page, { text: "# To be kept\n\nStays." });

  await page.goto("/documents");
  await page.getByRole("button", { name: "Delete To be deleted" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete for good" }).click();

  await expect(page.getByRole("link", { name: "To be deleted" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "To be kept", exact: true })).toBeVisible();
});
