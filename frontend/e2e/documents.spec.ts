import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { createDocument, editor, isContentSave, openPanel, signUp } from "./helpers";

const REPORT = "# Quarterly report\n\nRevenue grew in every quarter.\n\n## Costs\n\nCosts stayed flat.";

test.beforeEach(async ({ page }) => {
  await signUp(page);
});

test("create from pasted text: check the structure, fix it, then open the editor", async ({ page }) => {
  await page.goto("/new");
  await page.getByLabel("Your text").fill(REPORT);
  await page.getByRole("button", { name: "Analyse the structure" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Check the structure" })).toBeVisible();
  await expect(page.getByText("2 headings · 2 paragraphs · 0 other blocks")).toBeVisible();
  // "Costs" was read as a second-level heading; the user makes it a first-level one and names the project.
  await page.getByLabel("What “Costs” is").selectOption("h1");
  await page.getByLabel("Project name").fill("Quarterly report 2026");
  await page.getByRole("button", { name: "Confirm the structure" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Choose the look" })).toBeVisible();
  await page.getByRole("button", { name: "Open without formatting" }).click();
  await page.waitForURL(/\/documents\/[0-9a-f-]{36}$/);

  await expect(editor(page).getByRole("heading", { name: "Quarterly report", exact: true })).toBeVisible();
  await expect(editor(page).getByRole("heading", { level: 1, name: "Costs" })).toBeVisible();
  await expect(editor(page).getByText("Costs stayed flat.")).toBeVisible();
  await expect(page.getByText("Quarterly report 2026").first()).toBeVisible();
});

test("typing is saved on its own and is still there after a reload", async ({ page }) => {
  await createDocument(page, { text: REPORT });

  await editor(page).getByText("Costs stayed flat.").click();
  await page.keyboard.press("End");
  const saved = page.waitForResponse(isContentSave);
  await page.keyboard.type(" Next year too.");
  // What changed goes, not the document (PERF-003): the one paragraph typed in.
  const request = (await saved).request();
  expect(request.method()).toBe("PATCH");
  const patch = JSON.parse(request.postData() ?? "{}");
  expect(patch.changed.map((element: { content: string }) => element.content)).toEqual([expect.stringMatching(/^Costs stayed flat\./)]);
  expect(request.postData()).not.toContain("Revenue grew");
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();

  await page.reload();
  await expect(editor(page).getByText("Costs stayed flat. Next year too.")).toBeVisible();
});

test("choose a template, apply it, then undo and redo the formatting", async ({ page }) => {
  await createDocument(page, { text: REPORT });
  const body = editor(page).getByText("Revenue grew in every quarter.");
  await expect(body).not.toHaveCSS("font-family", /Times New Roman/);

  await openPanel(page, "Templates");
  await page.getByRole("button", { name: /Academic/ }).first().click();
  await page.getByRole("button", { name: "Apply formatting" }).click();
  await expect(body).toHaveCSS("font-family", /Times New Roman/);

  await openPanel(page, "Instructions");
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
    // The export's check: the file, read back, holds every word of the document.
    await expect(page.getByRole("status").filter({ hasText: "Every word of the document is in the file." })).toBeVisible();
    await page.getByRole("button", { name: "Export", exact: true }).click({ force: true }); // closes the menu
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

test("the Projects gallery: cards that open their document, no thumbnail asked for, no sideways scrolling on a phone (S2-025)", async ({ page }) => {
  const id = await createDocument(page, { text: "# Gallery one\n\nFirst." });
  await createDocument(page, { text: "# Gallery two\n\nSecond." });
  const thumbnails: string[] = [];
  page.on("request", (request) => {
    if (/\/documents\/[^/]+\/thumbnail/.test(request.url())) thumbnails.push(request.url());
  });

  for (const width of [1366, 390, 375]) {
    await page.setViewportSize({ width, height: 860 });
    await page.goto("/documents");
    const card = page.getByRole("listitem").filter({ has: page.getByRole("link", { name: "Gallery one", exact: true }) });
    await expect(card).toBeVisible();
    await expect(card.getByTestId("project-kind")).toBeVisible();
    await expect(card.getByRole("checkbox", { name: "Select Gallery one" })).toBeVisible();
    await expect(card.getByRole("link", { name: "Before and after: Gallery one" })).toBeVisible();
    await expect(card.getByRole("button", { name: "Delete Gallery one" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  }

  // The whole card opens the document; its tick doesn't.
  const card = page.getByRole("listitem").filter({ has: page.getByRole("link", { name: "Gallery one", exact: true }) });
  await card.getByRole("checkbox", { name: "Select Gallery one" }).check();
  await expect(page).toHaveURL(/\/documents$/);
  await expect(page.getByRole("region", { name: "Selected documents" }).getByText("1 selected")).toBeVisible();
  await card.getByTestId("project-kind").scrollIntoViewIfNeeded();
  const picture = (await card.getByTestId("project-kind").boundingBox())!;
  await page.mouse.click(picture.x + picture.width / 2, picture.y + picture.height / 2); // as a person would: the picture, under the card's link
  await expect(page).toHaveURL(new RegExp(`/documents/${id}$`));
  await page.waitForTimeout(500);
  expect(thumbnails).toEqual([]);
});
