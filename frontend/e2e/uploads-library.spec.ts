import { expect, test, type Page } from "@playwright/test";

import { API, createDocument, editor, isContentSave, openPanel, signUp, unzipped } from "./helpers";

/**
 * The Uploads panel (S2-131a): the pictures the workspace's documents already hold, in the left side panel of both
 * editors, put in another document with one click -- by the same asset, never stored again -- after the selected
 * block; saved, back after a reload, undone and redone, in the DOCX and PDF exports, kept when the document it came
 * from is deleted, and never another account's.
 */

const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
const TEXT = "First paragraph of the report.\n\nSecond paragraph of the report.";

type Stored = { id: string; elements: { type: string; image?: { assetId: string | null; src: string } }[] };

/** The document's blocks as the editor shows them (page-spacer widgets left out, e2e/image-insert.spec.ts). */
async function blocks(page: Page): Promise<string[]> {
  return editor(page).evaluate((root) =>
    Array.from(root.children)
      .filter((child) => !child.classList.contains("ProseMirror-widget"))
      .map((child) => (child.tagName === "IMG" || child.querySelector("img") ? "img" : (child.textContent ?? "").trim())),
  );
}

async function stored(page: Page, id: string): Promise<Stored> {
  return (await page.request.get(`${API}/documents/${id}`)).json();
}

function pictureIds(document: Stored): (string | null)[] {
  return document.elements.filter((one) => one.type === "image").map((one) => one.image!.assetId);
}

/** A document of the workspace that holds one picture (as one pasted into it): returns it and its picture's asset id. */
async function documentWithPicture(page: Page): Promise<{ id: string; assetId: string }> {
  const created: Stored = await (await page.request.post(`${API}/documents`, { data: { text: "# Source\n\nThe picture's first document." } })).json();
  const pasted = { type: "image", content: "", order: 99, image: { src: `data:image/png;base64,${PNG.toString("base64")}` } };
  const saved: Stored = await (await page.request.put(`${API}/documents/${created.id}/content`, { data: { elements: [...created.elements, pasted] } })).json();
  const [assetId] = pictureIds(saved);
  expect(assetId).toBeTruthy();
  return { id: created.id, assetId: assetId! };
}

async function listed(page: Page): Promise<string[]> {
  const answer = await (await page.request.get(`${API}/assets`)).json();
  return answer.items.map((item: { id: string }) => item.id);
}

test("the classic editor: a picture of another document goes in after the selected paragraph, as the same asset", async ({ page, browser }) => {
  await signUp(page);
  const source = await documentWithPicture(page);
  const id = await createDocument(page, { text: TEXT });
  await editor(page).getByText("First paragraph of the report.").click();

  await openPanel(page, "Uploads");
  const panel = page.getByTestId("uploads-panel");
  await expect(panel.getByText(/Pictures used in your documents/)).toBeVisible();
  const tile = panel.getByRole("button", { name: /^Insert picture 1 / });
  await expect(tile).toHaveAttribute("data-asset-id", source.assetId);
  await expect(tile.locator("img")).toHaveJSProperty("complete", true);
  expect(await tile.locator("img").evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(1);

  // From the keyboard: the tile is a button.
  await tile.focus();
  const save = page.waitForResponse(isContentSave);
  await page.keyboard.press("Enter");
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "img", "Second paragraph of the report."]);
  await save;
  await expect(panel.getByText("Picture inserted.")).toBeVisible();

  // Saved as the same asset: nothing stored again.
  expect(pictureIds(await stored(page, id))).toEqual([source.assetId]);
  expect(await listed(page)).toEqual([source.assetId]);

  // Undo takes it out and redo puts it back, each saved.
  let saved = page.waitForResponse(isContentSave);
  await page.keyboard.press("Control+z");
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "Second paragraph of the report."]);
  await saved;
  expect(pictureIds(await stored(page, id))).toEqual([]);
  saved = page.waitForResponse(isContentSave);
  await page.keyboard.press("Control+y");
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "img", "Second paragraph of the report."]);
  await saved;
  expect(pictureIds(await stored(page, id))).toEqual([source.assetId]);

  await page.reload();
  await expect(editor(page).locator("img")).toHaveAttribute("src", new RegExp(`/api/v1/assets/${source.assetId}$`));
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "img", "Second paragraph of the report."]);

  // The document it came from deleted: the picture stays -- served, listed and exported with this one.
  expect((await page.request.delete(`${API}/documents/${source.id}`)).status()).toBe(204);
  expect((await page.request.get(`${API}/assets/${source.assetId}`)).status()).toBe(200);
  expect(await listed(page)).toEqual([source.assetId]);
  const docx = Buffer.from(await (await page.request.get(`${API}/documents/${id}/export/docx`)).body());
  expect(unzipped(docx, "word/document.xml")).toContain("<w:drawing>");
  expect(unzipped(docx, "word/_rels/document.xml.rels")).toMatch(/Target="media\/[^"]+\.png"/);
  const pdf = Buffer.from(await (await page.request.get(`${API}/documents/${id}/export/pdf`)).body());
  expect(pdf.toString("latin1")).toMatch(/\/Subtype\s*\/Image/);

  // Another account lists none of it, and can't put it in a document of its own by its id.
  const other = await browser.newContext();
  const stranger = await other.newPage();
  await signUp(stranger);
  expect(await listed(stranger)).toEqual([]);
  const theirs: Stored = await (await stranger.request.post(`${API}/documents`, { data: { text: "# Theirs\n\nA paragraph of their own." } })).json();
  const planted = { type: "image", content: "", order: 99, image: { src: "", assetId: source.assetId } };
  const answer = await stranger.request.put(`${API}/documents/${theirs.id}/content`, { data: { elements: [...theirs.elements, planted] } });
  expect(answer.status()).toBe(200);
  expect(pictureIds(await answer.json())).toEqual([]);
  await stranger.goto(`/documents/${theirs.id}`);
  await openPanel(stranger, "Uploads");
  await expect(stranger.getByTestId("uploads-panel").getByText(/No pictures yet/)).toBeVisible();
  await other.close();
});

test("a picture the server doesn't keep goes from the page too, the person is told why, and Saved is true", async ({ page, browser }) => {
  // Another account's picture: the id a forged (or stale) save could carry.
  const other = await browser.newContext();
  const stranger = await other.newPage();
  await signUp(stranger);
  const foreign = await documentWithPicture(stranger);
  await other.close();

  await signUp(page);
  const source = await documentWithPicture(page);
  const id = await createDocument(page, { text: TEXT });
  // The save of this document carries the other account's id instead of the listed picture's.
  await page.route(`**/api/v1/documents/${id}/content`, (route) =>
    route.continue({ postData: (route.request().postData() ?? "").replaceAll(source.assetId, foreign.assetId) }),
  );
  await editor(page).getByText("First paragraph of the report.").click();
  await page.keyboard.type(" Typed");
  await openPanel(page, "Uploads");
  const save = page.waitForResponse(isContentSave);
  await page.getByTestId("uploads-panel").getByRole("button", { name: /^Insert picture 1 / }).click();
  await save;

  await expect(page.getByRole("alert").filter({ hasText: "A picture couldn't be saved and was taken out of the document" })).toBeVisible();
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report. Typed", "Second paragraph of the report."]);
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  const kept = await stored(page, id);
  expect(pictureIds(kept)).toEqual([]);
  expect(kept.elements.map((one) => (one as { content?: string }).content)).toContain("First paragraph of the report. Typed");

  await page.unroute(`**/api/v1/documents/${id}/content`);
  await page.reload();
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report. Typed", "Second paragraph of the report."]);
  await expect(editor(page).locator("img")).toHaveCount(0);
});

test("a tall picture put in from the panel sits whole inside one page (B-037)", async ({ page }) => {
  await signUp(page);
  const created: Stored = await (await page.request.post(`${API}/documents`, { data: { text: "# Source\n\nA tall screenshot." } })).json();
  const tall = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 946;
    canvas.height = 2048;
    const ctx = canvas.getContext("2d")!;
    for (let y = 0; y < 2048; y += 128) {
      ctx.fillStyle = `hsl(${(y / 8) % 360} 60% 60%)`;
      ctx.fillRect(0, y, 946, 64);
    }
    return canvas.toDataURL("image/png");
  });
  const pasted = { type: "image", content: "", order: 99, image: { src: tall } };
  expect((await page.request.put(`${API}/documents/${created.id}/content`, { data: { elements: [...created.elements, pasted] } })).status()).toBe(200);
  const id = await createDocument(page, { text: TEXT });
  await editor(page).getByText("First paragraph of the report.").click();
  await openPanel(page, "Uploads");
  const save = page.waitForResponse(isContentSave);
  await page.getByTestId("uploads-panel").getByRole("button", { name: /^Insert picture 1 / }).click();
  await save;

  // In the page layout's own px (zoom taken out), as e2e/image-pagination.spec.ts measures it.
  await expect
    .poll(() =>
      editor(page).evaluate((root) => {
        const container = root.closest<HTMLElement>("[data-page-height]")!;
        const scale = Number(container.dataset.scale) || 1;
        const origin = container.getBoundingClientRect().top;
        const img = root.querySelector("img");
        if (!img || !img.complete || img.naturalWidth === 0) return "not loaded";
        const box = img.getBoundingClientRect();
        const top = (box.top - origin) / scale;
        const bottom = (box.bottom - origin) / scale;
        const sheets = Array.from(container.querySelectorAll<HTMLElement>("[data-page]")).map((sheet) => ({ top: parseFloat(sheet.style.top), height: parseFloat(sheet.style.height) }));
        const sheet = sheets.find((one) => top >= one.top + Number(container.dataset.marginTop) - 1 && top < one.top + one.height);
        if (!sheet) return "outside every page";
        return bottom <= sheet.top + sheet.height - Number(container.dataset.marginBottom) + 1 ? "fits" : "crosses the page bottom";
      }),
    )
    .toBe("fits");
  expect(pictureIds(await stored(page, id))).toHaveLength(1);
});

test("Editor 2.0: the Uploads panel is in its rail and puts a picture in", async ({ page }) => {
  await signUp(page);
  const source = await documentWithPicture(page);
  const id = await createDocument(page, { text: TEXT });
  await page.goto(`/documents/${id}?editor=2`);
  await expect(editor(page)).toBeVisible();
  await editor(page).getByText("Second paragraph of the report.").click();

  await page.getByRole("navigation", { name: "Editor panels" }).getByRole("button", { name: "Open Uploads" }).click();
  const panel = page.getByRole("complementary", { name: "Uploads" });
  const save = page.waitForResponse(isContentSave);
  await panel.getByRole("button", { name: /^Insert picture 1 / }).click();
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "Second paragraph of the report.", "img", ""]);
  await save;
  expect(pictureIds(await stored(page, id))).toEqual([source.assetId]);
  expect(await listed(page)).toEqual([source.assetId]);
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("Editor 2.0: the panel opens from the panels menu, fits the screen and puts a picture in", async ({ page }) => {
    await signUp(page);
    const source = await documentWithPicture(page);
    const id = await createDocument(page, { text: TEXT });
    await page.goto(`/documents/${id}?editor=2`);
    await expect(editor(page)).toBeVisible();

    await page.getByRole("button", { name: "Editor panels" }).click();
    await page.getByRole("navigation", { name: "Editor panels" }).getByRole("button", { name: "Open Uploads" }).click();
    const panel = page.getByRole("complementary", { name: "Uploads" });
    const tile = panel.getByRole("button", { name: /^Insert picture 1 / });
    await expect(tile).toBeVisible();
    const box = (await tile.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(375);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

    const save = page.waitForResponse(isContentSave);
    await tile.click();
    await save;
    expect(pictureIds(await stored(page, id))).toEqual([source.assetId]);
  });

  test("the classic editor: the panel fits the screen", async ({ page }) => {
    await signUp(page);
    await documentWithPicture(page);
    await createDocument(page, { text: TEXT });
    await openPanel(page, "Uploads");
    await expect(page.getByTestId("uploads-panel").getByRole("button", { name: /^Insert picture 1 / })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
});

test.describe("in Bulgarian", () => {
  test("the panel and its pictures are named in Bulgarian, in both editors", async ({ page }) => {
    await signUp(page);
    await page.context().addCookies([{ name: "smartdoc_locale", value: "bg", url: "http://localhost:3100" }]);
    const source = await documentWithPicture(page);
    const created: Stored = await (await page.request.post(`${API}/documents`, { data: { text: TEXT } })).json();

    await page.goto(`/documents/${created.id}`);
    await expect(editor(page)).toBeVisible();
    await openPanel(page, "Качени изображения");
    const classic = page.getByTestId("uploads-panel");
    await expect(classic.getByText(/Изображения, използвани във вашите документи/)).toBeVisible();
    await expect(classic.getByRole("button", { name: /^Вмъкни изображение 1 / })).toHaveAttribute("data-asset-id", source.assetId);

    await page.goto(`/documents/${created.id}?editor=2`);
    await expect(editor(page)).toBeVisible();
    await page.getByRole("navigation", { name: "Панели на редактора" }).getByRole("button", { name: "Отвори Качени изображения" }).click();
    await expect(page.getByRole("complementary", { name: "Качени изображения" }).getByRole("button", { name: /^Вмъкни изображение 1 / })).toBeVisible();
  });
});
