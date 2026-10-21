import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { API, createDocument, editor, GOLDEN, isContentSave, PASSWORD, signUp, uniqueEmail } from "./helpers";

/**
 * The SmartDoc 2.0 editor shell (E1, docs/SMARTDOC_2_0_EDITOR_ARCHITECTURE.md), behind ?editor=2, on the same
 * engine as the classic editor: the same documents open, typing is saved, undo/redo, templates, export, and a
 * failed save says so and can be retried. The classic editor stays the default.
 */

const REPORT = "# Quarterly report\n\nRevenue grew in every quarter.\n\n## Costs\n\nCosts stayed flat.";

async function openV2(page: Page, id: string) {
  await page.goto(`/documents/${id}?editor=2`);
  await expect(page.getByRole("navigation", { name: "Editor panels" })).toBeVisible();
  await expect(editor(page)).toBeVisible();
}

const topBar = (page: Page) => page.locator("header");

test.describe("in English", () => {
  test.beforeEach(async ({ page }) => {
    await signUp(page);
  });

  test("the classic editor stays the default; ?editor=2 opens the new shell on the same document", async ({ page }) => {
    const id = await createDocument(page, { text: REPORT });
    await expect(page.getByRole("navigation", { name: "Editor panels" })).toHaveCount(0); // classic

    await openV2(page, id);
    await expect(editor(page).getByRole("heading", { name: "Quarterly report" })).toBeVisible();
    await expect(topBar(page).getByRole("link", { name: "Projects" })).toHaveAttribute("href", "/documents");
    await expect(topBar(page).getByRole("status")).toHaveText("Saved");
    await expect(page.getByRole("complementary", { name: "Properties" })).toBeVisible();
    await expect(page.getByRole("toolbar", { name: "Tools for the selection" })).toBeVisible();

    await page.getByRole("button", { name: "Open Structure" }).click();
    await expect(page.getByRole("complementary", { name: "Structure" })).toBeVisible();
    await page.getByRole("button", { name: "Close the panel" }).click();
    await expect(page.getByRole("complementary", { name: "Structure" })).toHaveCount(0);
  });

  test("typing is saved (a patch), shown in the top bar, and still there after a reload", async ({ page }) => {
    const id = await createDocument(page, { text: REPORT });
    await openV2(page, id);

    await editor(page).getByText("Costs stayed flat.").click();
    await page.keyboard.press("End");
    const saved = page.waitForResponse(isContentSave);
    await page.keyboard.type(" Next year too.");
    expect((await saved).request().method()).toBe("PATCH");
    await expect(topBar(page).getByRole("status")).toHaveText("Saved");

    await page.reload();
    await expect(editor(page).getByText("Costs stayed flat. Next year too.")).toBeVisible();
  });

  test("undo and redo of typing from the top bar; what is saved is what's on the page", async ({ page }) => {
    const id = await createDocument(page, { text: REPORT });
    await openV2(page, id);

    await editor(page).getByText("Costs stayed flat.").click();
    await page.keyboard.press("End");
    await page.keyboard.type(" Temporary.");
    await page.getByRole("button", { name: "Undo typing" }).click();
    await expect(editor(page).getByText("Costs stayed flat.", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Redo typing" }).click();
    await expect(editor(page).getByText("Costs stayed flat. Temporary.")).toBeVisible();
    const saved = page.waitForResponse(isContentSave);
    await page.getByRole("button", { name: "Undo typing" }).click();
    await saved;
    await expect(topBar(page).getByRole("status")).toHaveText("Saved");

    await page.reload();
    await expect(editor(page).getByText("Costs stayed flat.", { exact: true })).toBeVisible();
  });

  test("templates from the rail, then undo and redo of the formatting", async ({ page }) => {
    const id = await createDocument(page, { text: REPORT });
    await openV2(page, id);
    const body = editor(page).getByText("Revenue grew in every quarter.");
    await expect(body).not.toHaveCSS("font-family", /Times New Roman/);

    await page.getByRole("button", { name: "Open Templates" }).click();
    await page.getByRole("complementary", { name: "Templates" }).getByRole("button", { name: /Academic/ }).first().click();
    await page.getByRole("button", { name: "Apply formatting" }).click();
    await expect(body).toHaveCSS("font-family", /Times New Roman/);

    // One Undo/Redo, in the top bar: the Instructions panel has no second pair in this editor.
    await page.getByRole("button", { name: "Open Instructions" }).click();
    await expect(page.getByRole("button", { name: "Undo formatting" })).toHaveCount(0);
    await page.getByRole("button", { name: "Undo the last saved change" }).click();
    await expect(body).not.toHaveCSS("font-family", /Times New Roman/);
    await page.getByRole("button", { name: "Redo the next saved change" }).click();
    await expect(body).toHaveCSS("font-family", /Times New Roman/);
  });

  test("export to Word and to PDF from the new top bar, each file checked", async ({ page }) => {
    const id = await createDocument(page, { text: REPORT });
    await openV2(page, id);

    for (const [format, signature] of [
      ["DOCX", "PK"],
      ["PDF", "%PDF"],
    ] as const) {
      await page.getByRole("button", { name: "Export", exact: true }).click();
      await page.getByRole("button", { name: format, exact: true }).click();
      const download = page.waitForEvent("download");
      await page.getByRole("button", { name: `Download ${format}` }).click();
      const file = await download;
      expect(readFileSync((await file.path())!).subarray(0, signature.length).toString("latin1")).toBe(signature);
      await expect(page.getByRole("status").filter({ hasText: "Every word of the document is in the file." })).toBeVisible();
      await page.getByRole("button", { name: "Export", exact: true }).click({ force: true }); // closes the menu
    }
  });

  test("an imported Word document opens in the new shell with its content", async ({ page }) => {
    const id = await createDocument(page, { file: path.join(GOLDEN, "12-complex.docx") });
    const classicText = await editor(page).innerText();
    await openV2(page, id);
    await expect.poll(async () => (await editor(page).innerText()).length).toBeGreaterThan(0);
    expect(await editor(page).innerText()).toBe(classicText);
  });

  test("a failed save says so in the top bar, and Retry saves it", async ({ page }) => {
    const id = await createDocument(page, { text: REPORT });
    await openV2(page, id);
    // The server refuses the next saves.
    await page.route("**/documents/*/content", (route) => route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ code: "internal", message: "Boom", details: null, request_id: "e2e" }) }));

    await editor(page).getByText("Costs stayed flat.").click();
    await page.keyboard.press("End");
    await page.keyboard.type(" Not yet saved.");
    // The failed save (it offers Retry), not "Not saved yet" (typed, the save not started).
    await expect(topBar(page).getByRole("button", { name: "Retry" })).toBeVisible({ timeout: 15_000 });
    await expect(topBar(page).getByRole("status")).toContainText(/^Not saved(?! yet)/);

    await page.unroute("**/documents/*/content");
    const saved = page.waitForResponse(isContentSave);
    await topBar(page).getByRole("button", { name: "Retry" }).click();
    await saved;
    await expect(topBar(page).getByRole("status")).toHaveText("Saved");
    await page.reload();
    await expect(editor(page).getByText("Costs stayed flat. Not yet saved.")).toBeVisible();
  });

  // ---------------------------------------------------------------- E2: selection, commands, one undo, layout

  test("one undo: typing first, then the saved template change -- said in words, never undone twice", async ({ page }) => {
    const id = await createDocument(page, { text: REPORT });
    await openV2(page, id);
    const body = editor(page).getByText(/^Revenue grew in every quarter\./);
    await page.getByRole("button", { name: "Open Templates" }).click();
    await page.getByRole("complementary", { name: "Templates" }).getByRole("button", { name: /Academic/ }).first().click();
    await page.getByRole("button", { name: "Apply formatting" }).click();
    await expect(body).toHaveCSS("font-family", /Times New Roman/);

    await body.click();
    await page.keyboard.press("End");
    await page.keyboard.type(" Extra.");
    // Ctrl+Z in the text: the typing goes first, the template stays.
    await page.keyboard.press("Control+z");
    await expect(editor(page).getByText("Revenue grew in every quarter.", { exact: true })).toBeVisible();
    await expect(body).toHaveCSS("font-family", /Times New Roman/);
    // Nothing typed is left: the next undo is the saved change, on the server, and it says which.
    await expect(page.getByRole("button", { name: "Undo the last saved change" })).toBeEnabled();
    await page.getByRole("button", { name: "Undo the last saved change" }).click();
    await expect(body).not.toHaveCSS("font-family", /Times New Roman/);
    await expect(page.getByRole("status").filter({ hasText: /^Undone: / })).toBeVisible();
    await page.getByRole("button", { name: "Redo the next saved change" }).click();
    await expect(body).toHaveCSS("font-family", /Times New Roman/);
  });

  test("the toolbar follows the selection: text tools, table tools inside a table, picture tools for a picture", async ({ page }) => {
    const id = await createDocument(page, { file: path.join(GOLDEN, "17-pictures.docx") });
    await openV2(page, id);
    const toolbar = page.getByRole("toolbar", { name: "Tools for the selection" });

    await editor(page).locator("p").first().click();
    await expect(toolbar.getByRole("button", { name: "Bold" })).toBeVisible();
    await expect(toolbar.getByRole("group", { name: "Table" })).toHaveCount(0);

    await editor(page).locator("img").first().click();
    await expect(toolbar.getByRole("group", { name: "Picture" })).toBeVisible();
    await expect(toolbar.getByRole("button", { name: "Bold" })).toHaveCount(0);

    const table = await createDocument(page, { file: path.join(GOLDEN, "03-tables.docx") });
    await openV2(page, table);
    await editor(page).locator("td p").first().click();
    await expect(toolbar.getByRole("group", { name: "Table" })).toBeVisible();
    await expect(toolbar.getByRole("button", { name: "Bold" })).toBeVisible();
    const rows = await editor(page).locator("tr").count();
    await toolbar.getByRole("button", { name: "Row below" }).click();
    await expect(editor(page).locator("tr")).toHaveCount(rows + 1);
  });

  test("the toolbar is one tab stop; arrow keys move between its tools, and the button keeps the text selected", async ({ page }) => {
    const id = await createDocument(page, { text: REPORT });
    await openV2(page, id);
    // The line selected with the keyboard (a click in the middle of a short paragraph lands past its text).
    await editor(page).getByText("Costs stayed flat.").click();
    await page.keyboard.press("Home");
    await page.keyboard.press("Shift+End");
    await page.getByRole("toolbar", { name: "Tools for the selection" }).getByRole("button", { name: "Bold" }).click();
    await expect(editor(page).locator("strong")).toHaveText("Costs stayed flat.");
    await page.getByRole("toolbar", { name: "Tools for the selection" }).focus();
    const first = await page.evaluate(() => document.activeElement?.getAttribute("aria-label"));
    await page.keyboard.press("ArrowRight");
    const second = await page.evaluate(() => document.activeElement?.getAttribute("aria-label"));
    expect(first).toBeTruthy();
    expect(second).not.toBe(first);
  });

  test("panels hide with one button or Ctrl+\\, the page gets the room, and it is remembered", async ({ page }) => {
    const id = await createDocument(page, { text: REPORT });
    await openV2(page, id);
    const main = page.getByRole("main", { name: "Pages" });
    const before = (await main.boundingBox())!.width;
    await page.getByRole("button", { name: "Hide the panels" }).click();
    await expect(page.getByRole("navigation", { name: "Editor panels" })).toHaveCount(0);
    await expect(page.getByRole("complementary", { name: "Properties" })).toHaveCount(0);
    expect((await main.boundingBox())!.width).toBeGreaterThan(before + 200);

    await page.reload();
    await expect(page.getByRole("button", { name: "Show the panels" })).toBeVisible();
    await page.keyboard.press("Control+\\");
    await expect(page.getByRole("navigation", { name: "Editor panels" })).toBeVisible();
  });
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("reading: the page fits the width, page x of y, previous/next, zoom", async ({ page }) => {
    await signUp(page);
    const long = `# Long\n\n${Array.from({ length: 60 }, (_, index) => `Paragraph ${index + 1} with enough words to fill a line or two on the page.`).join("\n\n")}`;
    const id = await createDocument(page, { text: long });
    await page.goto(`/documents/${id}?editor=2`);
    await expect(editor(page)).toBeVisible();
    const reading = page.getByRole("navigation", { name: "Pages" });
    await expect(reading.getByText(/^Page 1 of [2-9]/)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

    await reading.getByRole("button", { name: "Next page" }).click();
    await expect(reading.getByText(/^Page 2 of/)).toBeVisible();
    await reading.getByRole("button", { name: "Previous page" }).click();
    await expect(reading.getByText(/^Page 1 of/)).toBeVisible();

    const zoom = reading.getByText(/^\d+%$/);
    const fit = await zoom.innerText();
    await reading.getByRole("button", { name: "Zoom in" }).click();
    await expect(zoom).not.toHaveText(fit);
    await reading.getByRole("button", { name: "Fit width" }).click();
    await expect(zoom).toHaveText(fit);
  });
});

test.describe("in Bulgarian", () => {
  test.use({ locale: "bg-BG" });

  test("the new shell speaks Bulgarian", async ({ page }) => {
    await page.goto("/register");
    await page.getByLabel("Имейл").fill(uniqueEmail("bg"));
    await page.getByLabel("Парола").fill(PASSWORD);
    await page.getByRole("button", { name: "Създай акаунт" }).click();
    await expect(page.getByRole("heading", { name: /Добре дошли отново/ })).toBeVisible();
    const created = await page.request.post(`${API}/documents`, { data: { text: REPORT, title: "Отчет" }, headers: { Origin: "http://localhost:3100" } });
    const { id } = (await created.json()) as { id: string };

    await page.goto(`/documents/${id}?editor=2`);
    await expect(page.getByRole("navigation", { name: "Панели на редактора" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Отвори Шаблони" })).toBeVisible();
    await expect(page.locator("header").getByRole("status")).toHaveText("Запазено");
    await expect(page.getByRole("button", { name: "Отмени писането" })).toBeVisible();

    // The panels' own words too, not only the frame around them.
    await page.getByRole("button", { name: "Отвори Шаблони" }).click();
    await expect(page.getByRole("button", { name: "Приложи форматирането" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Без шаблон" })).toBeVisible();
    await page.getByRole("button", { name: "Отвори История" }).click();
    await expect(page.getByRole("link", { name: /Преди и след/ })).toBeVisible();
    await page.getByRole("button", { name: "Експорт", exact: true }).click();
    await expect(page.getByRole("button", { name: "Изтегли DOCX" })).toBeVisible();
  });
});
