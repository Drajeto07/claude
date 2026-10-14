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
    await expect(page.getByRole("toolbar", { name: "Text tools" })).toBeVisible();

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
    await page.getByRole("complementary", { name: "Templates" }).getByRole("button", { name: /Академичен/ }).first().click();
    await page.getByRole("button", { name: "Apply formatting" }).click();
    await expect(body).toHaveCSS("font-family", /Times New Roman/);

    await page.getByRole("button", { name: "Open Instructions" }).click();
    await page.getByRole("button", { name: "Undo formatting" }).click();
    await expect(body).not.toHaveCSS("font-family", /Times New Roman/);
    await page.getByRole("button", { name: "Redo formatting" }).click();
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
    await expect(topBar(page).getByRole("status")).toContainText("Not saved", { timeout: 15_000 });

    await page.unroute("**/documents/*/content");
    const saved = page.waitForResponse(isContentSave);
    await topBar(page).getByRole("button", { name: "Retry" }).click();
    await saved;
    await expect(topBar(page).getByRole("status")).toHaveText("Saved");
    await page.reload();
    await expect(editor(page).getByText("Costs stayed flat. Not yet saved.")).toBeVisible();
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
  });
});
