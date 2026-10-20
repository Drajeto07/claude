import { expect, test, type Locator, type Page } from "@playwright/test";

import { API, editor, signUp } from "./helpers";

/**
 * Stage 2: the classic editor on a phone. At 375 and 390 px nothing in its top bar runs off the screen, its
 * bottom bars don't run into each other, the text is drawn at a readable size and every tool can be reached;
 * at desktop width it is as it was.
 */

const TEXT = "# Quarterly report on regional sales\n\nThe first quarter closed above plan in every region we track.\n\n## Results\n\nRevenue grew in every region.";

/** A document made through the API with the page's own session (the creation flow isn't under test here). */
async function openDocument(page: Page): Promise<void> {
  await signUp(page);
  const job = await (await page.request.post(`${API}/jobs/import-text`, { data: { text: TEXT, title: "Quarterly report on regional sales" } })).json();
  let id: string | undefined;
  await expect
    .poll(async () => {
      const state = await (await page.request.get(`${API}/jobs/${job.id}`)).json();
      id = state.status === "succeeded" ? state.result?.documentId : undefined;
      return id;
    })
    .toBeTruthy();
  await page.goto(`/documents/${id}`);
  await expect(editor(page)).toBeVisible();
}

async function box(locator: Locator) {
  const found = await locator.boundingBox();
  expect(found, "the element is laid out").not.toBeNull();
  return found!;
}

function overlap(a: { x: number; y: number; width: number; height: number }, b: typeof a): boolean {
  return Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x) > 1 && Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y) > 1;
}

/** The size the first paragraph's text is drawn at on screen, CSS px (its font size times the page's zoom). */
const drawnTextSize = (page: Page) =>
  editor(page)
    .locator("p")
    .first()
    .evaluate((paragraph) => parseFloat(getComputedStyle(paragraph).fontSize) * (paragraph.getBoundingClientRect().height / (paragraph as HTMLElement).offsetHeight));

for (const width of [375, 390]) {
  test.describe(`the classic editor at ${width} px`, () => {
    test.use({ viewport: { width, height: 812 } });

    test("the top bar fits: logo, title, export and the account are all on the screen", async ({ page }) => {
      await openDocument(page);
      const header = page.locator("header");
      const items = [
        header.getByRole("link", { name: "SmartDoc" }),
        header.getByTitle("Rename document"), // the title button, named by the document's title
        header.getByRole("button", { name: "Export" }),
        header.getByRole("link", { name: "Your account" }),
        header.getByRole("link", { name: "Plan and billing" }),
        header.getByRole("button", { name: "Sign out" }),
      ];
      const boxes = [];
      for (const item of items) {
        await expect(item).toBeVisible();
        const found = await box(item);
        expect(found.x).toBeGreaterThanOrEqual(0);
        expect(found.x + found.width).toBeLessThanOrEqual(width);
        boxes.push(found);
      }
      for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) expect(overlap(boxes[i], boxes[j]), `top bar items ${i} and ${j}`).toBe(false);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    });

    test("the text is drawn at a readable size, and 'Fit width' still shows the whole page", async ({ page }) => {
      await openDocument(page);
      await expect.poll(() => drawnTextSize(page)).toBeGreaterThanOrEqual(10);
      await page.getByRole("button", { name: "Fit width" }).click();
      await expect.poll(() => drawnTextSize(page)).toBeLessThan(8);
    });

    test("every tool can be reached, and the bottom bars neither cover the page nor each other", async ({ page }) => {
      await openDocument(page);
      const checklist = page.getByRole("button", { name: "Checklist" });
      await checklist.scrollIntoViewIfNeeded();
      await expect(checklist).toBeInViewport();

      const status = page.getByRole("status").first();
      const bar = page.locator(".border-t").filter({ has: status });
      const parts = [bar.getByRole("button", { name: "New page" }), status, bar.getByRole("button", { name: "Zoom out" }), bar.getByRole("button", { name: "Zoom in" }), bar.getByRole("button", { name: "Fit width" })];
      const boxes = [];
      for (const part of parts) {
        const found = await box(part);
        expect(found.x + found.width).toBeLessThanOrEqual(width);
        boxes.push(found);
      }
      for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) expect(overlap(boxes[i], boxes[j]), `bottom bar parts ${i} and ${j}`).toBe(false);

      // The pages' scrolling area ends where the bars below it begin.
      const desk = await box(page.locator(".overflow-y-auto").filter({ has: page.locator(".paged-editor") }));
      const assistant = await box(page.getByRole("button", { name: "Save now" }));
      expect(desk.y + desk.height).toBeLessThanOrEqual(assistant.y);
      expect(desk.height).toBeGreaterThan(400);
    });
  });
}

test.describe("the classic editor at desktop width", () => {
  test.use({ viewport: { width: 1366, height: 860 } });

  test("is as it was: the full logo, Export with its word, the hint and the tools without scrolling", async ({ page }) => {
    await openDocument(page);
    const header = page.locator("header");
    await expect(header.getByText("SmartDoc", { exact: true })).toBeVisible();
    await expect(header.getByRole("button", { name: "Export" })).toHaveText(/Export/);
    await expect(page.getByText(/Edits save automatically/)).toBeVisible();
    const tools = page.getByRole("button", { name: "Checklist" }).locator("..");
    expect(await tools.evaluate((row) => row.scrollWidth <= row.clientWidth)).toBe(true);
    await expect(tools.getByRole("combobox", { name: "Font" })).toBeInViewport();
    await expect(page.getByRole("button", { name: "New page" })).toHaveText(/New page/);
  });
});
