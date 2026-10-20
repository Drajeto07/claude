import path from "node:path";
import { readFileSync } from "node:fs";

import { expect, test, type Locator, type Page } from "@playwright/test";

import { API, editor, GOLDEN, isContentSave, signUp } from "./helpers";

/**
 * The classic editor on a phone. Stage 2A: at 375 and 390 px nothing in its top bar runs off the screen and its
 * bottom bar doesn't run into itself. Stage 2B: it opens in a writing view -- the same text and editor fitted to
 * the screen, read and edited without scrolling sideways, saved as always -- and "Page" still shows the pages.
 * At desktop width it is as it was. B-029: in the dark theme its white pages carry the light theme's dark text.
 */

const TEXT =
  "# Quarterly report on regional sales\n\nThe first quarter closed above plan in every region we track, and the second has started the same way.\n\n## Results\n\nRevenue grew in every region.";

async function waitForJob(page: Page, job: { id: string }): Promise<string> {
  let id: string | undefined;
  await expect
    .poll(async () => {
      const state = await (await page.request.get(`${API}/jobs/${job.id}`)).json();
      id = state.status === "succeeded" ? state.result?.documentId : undefined;
      return id;
    })
    .toBeTruthy();
  return id!;
}

/** A document made through the API with the page's own session (the creation flow isn't under test here). */
async function openDocument(page: Page, file?: string): Promise<string> {
  await signUp(page);
  const job = file
    ? await (await page.request.post(`${API}/jobs/import-file`, { multipart: { file: { name: path.basename(file), mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: readFileSync(file) } } })).json()
    : await (await page.request.post(`${API}/jobs/import-text`, { data: { text: TEXT, title: "Quarterly report on regional sales" } })).json();
  const id = await waitForJob(page, job);
  await page.goto(`/documents/${id}`);
  await expect(editor(page)).toBeVisible();
  return id;
}

async function box(locator: Locator) {
  const found = await locator.boundingBox();
  expect(found, "the element is laid out").not.toBeNull();
  return found!;
}

function overlap(a: { x: number; y: number; width: number; height: number }, b: typeof a): boolean {
  return Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x) > 1 && Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y) > 1;
}

/** The size a block's text is drawn at on screen, CSS px (its font size times any zoom). */
const drawnTextSize = (block: Locator) =>
  block.evaluate((element) => parseFloat(getComputedStyle(element).fontSize) * (element.getBoundingClientRect().height / (element as HTMLElement).offsetHeight));

const viewButton = (page: Page, name: "Writing" | "Page") => page.getByRole("group", { name: "View" }).getByRole("button", { name });

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

    test("opens in the writing view: whole lines on the screen, text 14-16 px, no sideways scrolling", async ({ page }) => {
      await openDocument(page);
      await expect(viewButton(page, "Writing")).toHaveAttribute("aria-pressed", "true");
      const sheet = page.locator(".paged-editor");
      await expect(sheet).toHaveClass(/\bflow\b/);
      const paragraph = editor(page).locator("p").filter({ hasText: "The first quarter" });
      const size = await drawnTextSize(paragraph);
      expect(size).toBeGreaterThanOrEqual(14);
      expect(size).toBeLessThanOrEqual(16);
      // The paragraph wraps inside the screen: every line within it, nothing to scroll to.
      const lines = await box(paragraph);
      expect(lines.x).toBeGreaterThanOrEqual(0);
      expect(lines.x + lines.width).toBeLessThanOrEqual(width);
      expect(lines.height).toBeGreaterThan(size * 2); // more than one line: reflowed, not cut
      const desk = page.locator(".overflow-y-auto").filter({ has: sheet });
      expect(await desk.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      // No pages, headers or zoom here.
      await expect(page.locator("[data-page]")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Zoom in" })).toHaveCount(0);
    });

    test("typing, deleting and bold in the writing view are saved and still there after a reload", async ({ page }) => {
      await openDocument(page);
      const paragraph = editor(page).locator("p").filter({ hasText: "Revenue grew" });
      await paragraph.click();
      await page.keyboard.press("End");
      const saved = page.waitForResponse((response) => isContentSave(response) && (response.request().postData() ?? "").includes("on a phone"));
      await page.keyboard.type(" Typed on a phoneXX", { delay: 10 });
      await page.keyboard.press("Backspace");
      await page.keyboard.press("Backspace");
      await saved;
      // Bold on the word just typed.
      await page.keyboard.down("Shift");
      for (let i = 0; i < "phone".length; i++) await page.keyboard.press("ArrowLeft");
      await page.keyboard.up("Shift");
      const bold = page.waitForResponse(isContentSave);
      await page.getByRole("button", { name: "Bold" }).first().click();
      await bold;
      await expect(page.getByRole("status").first()).toHaveText(/Saved/, { timeout: 15_000 });

      await page.reload();
      await expect(editor(page)).toBeVisible();
      const kept = editor(page).locator("p").filter({ hasText: "Revenue grew" });
      await expect(kept).toHaveText("Revenue grew in every region. Typed on a phone");
      await expect(kept.locator("strong")).toHaveText("phone");
    });

    test("a change from a second tab is still a conflict in the writing view, and nothing is overwritten", async ({ page, context }) => {
      const id = await openDocument(page);
      const second = await context.newPage();
      await second.goto(`/documents/${id}`);
      await expect(editor(second)).toBeVisible();
      const target = (p: Page) => editor(p).locator("p").filter({ hasText: "Revenue grew" });
      await target(second).click();
      await second.keyboard.press("End");
      const saved = second.waitForResponse(isContentSave);
      await second.keyboard.type(" from-the-second-tab");
      await saved;

      await target(page).click();
      await page.keyboard.press("End");
      await page.keyboard.type(" from-the-first-tab");
      await expect(page.getByText(/changed in another tab or window/).first()).toBeVisible({ timeout: 20_000 });
      await second.reload();
      await expect(editor(second).getByText(/from-the-second-tab/)).toBeVisible();
      await expect(editor(second).getByText(/from-the-first-tab/)).toHaveCount(0);
    });

    test("pictures fit the width and a wide table scrolls on its own", async ({ page }) => {
      await openDocument(page, path.join(GOLDEN, "17-pictures.docx"));
      const sheet = await box(page.locator(".paged-editor"));
      const pictures = editor(page).locator("img");
      await expect(pictures.first()).toBeVisible();
      for (const picture of await pictures.all()) {
        const found = await picture.boundingBox();
        if (found) expect(found.width).toBeLessThanOrEqual(sheet.width + 1);
      }
      const table = editor(page).locator("table").first();
      await expect(table).toBeVisible();
      const tableBox = await box(table);
      expect(tableBox.x + tableBox.width).toBeLessThanOrEqual(sheet.x + sheet.width + 1);
      const desk = page.locator(".overflow-y-auto").filter({ has: page.locator(".paged-editor") });
      expect(await desk.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    });

    test("switching views saves nothing; 'Page' shows the pages, readable, and 'Fit width' the whole page", async ({ page }) => {
      await openDocument(page);
      let saves = 0;
      page.on("request", (request) => {
        if (request.url().endsWith("/content") && request.method() !== "GET") saves += 1;
      });
      await viewButton(page, "Page").click();
      await expect(page.locator(".paged-editor")).not.toHaveClass(/\bflow\b/);
      await expect(page.locator("[data-page]").first()).toBeAttached();
      const heading = editor(page).locator("p").first();
      await expect.poll(() => drawnTextSize(heading)).toBeGreaterThanOrEqual(10);
      await page.getByRole("button", { name: "Fit width" }).click();
      await expect.poll(() => drawnTextSize(heading)).toBeLessThan(8);
      await viewButton(page, "Writing").click();
      await expect(page.locator(".paged-editor")).toHaveClass(/\bflow\b/);
      await page.waitForTimeout(1500);
      expect(saves).toBe(0);
    });

    test("in the dark theme the writing view is still white paper with dark text, headings, caret and links", async ({ page }) => {
      await page.context().addCookies([{ name: "smartdoc_theme", value: "dark", url: "http://localhost:3100" }]);
      await openDocument(page);
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
      const sheet = page.locator(".paged-editor");
      await expect(sheet).toHaveClass(/\bflow\b/);
      expect(await sheet.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe("rgb(255, 255, 255)");
      const dark = "rgb(15, 23, 42)";
      for (const block of [editor(page).locator("h1, h2").first(), editor(page).locator("p").filter({ hasText: "The first quarter" })]) {
        expect(await block.evaluate((element) => getComputedStyle(element).color)).toBe(dark);
      }
      expect(await editor(page).evaluate((element) => getComputedStyle(element).caretColor)).toBe(dark);
    });

    test("in the dark theme the Page view's white pages carry dark text, headings and caret; Writing again as it was (B-029)", async ({ page }) => {
      await page.context().addCookies([{ name: "smartdoc_theme", value: "dark", url: "http://localhost:3100" }]);
      await openDocument(page);
      await viewButton(page, "Page").click();
      await expect(page.locator(".paged-editor")).not.toHaveClass(/\bflow\b/);
      const ink = "rgb(16, 24, 40)"; // the light theme's text colour
      for (const block of [editor(page).locator("h1, h2").first(), editor(page).locator("p").filter({ hasText: "The first quarter" })]) {
        await expect(block).toHaveCSS("color", ink);
      }
      await expect(editor(page)).toHaveCSS("caret-color", ink);
      await expect(editor(page)).toHaveCSS("color-scheme", "light"); // selection drawn as on a light page
      await viewButton(page, "Writing").click();
      await expect(page.locator(".paged-editor")).toHaveClass(/\bflow\b/);
      await expect(editor(page).locator("p").filter({ hasText: "The first quarter" })).toHaveCSS("color", "rgb(15, 23, 42)");
    });

    test("switching Writing -> Page -> Writing before a save is done loses nothing: text and bold kept after a reload", async ({ page }) => {
      await openDocument(page);
      const status = page.getByRole("status").first();
      const paragraph = editor(page).locator("p").filter({ hasText: "Revenue grew" });
      await paragraph.click();
      await page.keyboard.press("Control+End"); // the end of the paragraph (the document's last), not of its first line on the screen
      // Typed, the save not started yet (the debounce): switch there and back at once.
      await page.keyboard.type(" plain ");
      await page.keyboard.press("Control+b");
      await page.keyboard.type("boldword");
      await page.keyboard.press("Control+b");
      await expect(status).toHaveText(/Not saved yet/);
      await viewButton(page, "Page").click();
      await viewButton(page, "Writing").click();
      await expect(status).toHaveText(/Saved/, { timeout: 15_000 });

      // Typed again, and the save on its way (held back a moment): switch there and back while it is.
      let release: () => void = () => undefined;
      const held = new Promise<void>((resolve) => (release = resolve));
      await page.route(/\/content$/, async (route) => {
        if (route.request().method() !== "GET") await held;
        await route.continue();
      });
      await paragraph.click();
      await page.keyboard.press("Control+End"); // the end of the paragraph (the document's last), not of its first line on the screen
      const sent = page.waitForRequest((request) => request.url().endsWith("/content") && request.method() !== "GET");
      await page.keyboard.type(" tail");
      await sent;
      await viewButton(page, "Page").click();
      await viewButton(page, "Writing").click();
      const saved = page.waitForResponse(isContentSave);
      release();
      await saved;
      await expect(status).toHaveText(/Saved/, { timeout: 15_000 });
      await page.unroute(/\/content$/);
      const onScreen = await paragraph.innerHTML();

      await page.reload();
      await expect(editor(page)).toBeVisible();
      const kept = editor(page).locator("p").filter({ hasText: "Revenue grew" });
      await expect(kept).toHaveText("Revenue grew in every region. plain boldword tail");
      // Whether " tail", typed straight after the bold word, is bold too depends on which side of the bold's edge
      // the browser puts the caret (as in Word); either way the reloaded paragraph is the one that was on screen.
      await expect(kept.locator("strong")).toHaveText(/^boldword( tail)?$/);
      expect(await kept.innerHTML()).toBe(onScreen);
    });

    test("every tool can be reached, and the bottom bars neither cover the page nor each other", async ({ page }) => {
      await openDocument(page);
      const checklist = page.getByRole("button", { name: "Checklist" });
      await checklist.scrollIntoViewIfNeeded();
      await expect(checklist).toBeInViewport();

      const status = page.getByRole("status").first();
      const bar = page.locator(".border-t").filter({ has: status });
      const parts = [bar.getByRole("button", { name: "New page" }), status, viewButton(page, "Writing"), viewButton(page, "Page")];
      const boxes = [];
      for (const part of parts) {
        const found = await box(part);
        expect(found.x + found.width).toBeLessThanOrEqual(width);
        boxes.push(found);
      }
      for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) expect(overlap(boxes[i], boxes[j]), `bottom bar parts ${i} and ${j}`).toBe(false);

      // The text's scrolling area ends where the bars below it begin.
      const desk = await box(page.locator(".overflow-y-auto").filter({ has: page.locator(".paged-editor") }));
      const assistant = await box(page.getByRole("button", { name: "Save now" }));
      expect(desk.y + desk.height).toBeLessThanOrEqual(assistant.y);
      expect(desk.height).toBeGreaterThan(400);
    });
  });
}

test.describe("the classic editor at desktop width", () => {
  test.use({ viewport: { width: 1366, height: 860 } });

  test("is as it was: pages, the full logo, Export with its word, the hint and the tools without scrolling", async ({ page }) => {
    await openDocument(page);
    const header = page.locator("header");
    await expect(header.getByText("SmartDoc", { exact: true })).toBeVisible();
    await expect(header.getByRole("button", { name: "Export" })).toHaveText(/Export/);
    await expect(page.getByText(/Edits save automatically/)).toBeVisible();
    await expect(page.locator(".paged-editor")).not.toHaveClass(/\bflow\b/);
    await expect(page.locator("[data-page]").first()).toBeAttached();
    await expect(page.getByRole("group", { name: "View" })).toHaveCount(0);
    const tools = page.getByRole("button", { name: "Checklist" }).locator("..");
    expect(await tools.evaluate((row) => row.scrollWidth <= row.clientWidth)).toBe(true);
    await expect(tools.getByRole("combobox", { name: "Font" })).toBeInViewport();
    await expect(page.getByRole("button", { name: "New page" })).toHaveText(/New page/);
  });

  /** The colours a page shows: the first paragraph, the first heading, a link, the caret, the first header line. */
  const pageColours = (page: Page) =>
    page.evaluate(() => {
      const root = document.querySelector(".paged-editor .ProseMirror")!;
      const colour = (element: Element | null) => (element ? getComputedStyle(element).color : null);
      return {
        text: colour(root.querySelector("p")),
        heading: colour(root.querySelector("h1, h2, h3")),
        link: colour(root.querySelector("a")),
        caret: getComputedStyle(root).caretColor,
        header: colour(document.querySelector('[data-page] [data-part="header"]')),
      };
    });
  const LIGHT_PAGE = { text: "rgb(16, 24, 40)", heading: "rgb(54, 95, 145)", link: "rgb(37, 99, 235)", caret: "rgb(16, 24, 40)", header: "rgb(88, 97, 116)" };

  test("the pages read the same in both themes: dark text, the document's heading colour, blue links, grey header (B-029)", async ({ page }) => {
    await openDocument(page, path.join(GOLDEN, "12-complex.docx"));
    await expect(page.locator("[data-page]").first()).toBeAttached();
    expect(await pageColours(page)).toEqual(LIGHT_PAGE);
    await page.context().addCookies([{ name: "smartdoc_theme", value: "dark", url: "http://localhost:3100" }]);
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(editor(page)).toBeVisible();
    expect(await pageColours(page)).toEqual(LIGHT_PAGE);
    await expect(editor(page)).toHaveCSS("color-scheme", "light");
  });

  test("in the dark theme a colour the document gives its text stays its own (B-029)", async ({ page }) => {
    await page.context().addCookies([{ name: "smartdoc_theme", value: "dark", url: "http://localhost:3100" }]);
    await openDocument(page, path.join(GOLDEN, "02-rich-text.docx"));
    const red = editor(page).locator("span[style*='color']").filter({ hasText: /\S/ }).first();
    await expect(red).toHaveCSS("color", "rgb(192, 0, 0)");
    await expect(editor(page).locator("p").first()).toHaveCSS("color", "rgb(16, 24, 40)");
  });

  test("the 2.0 editor's pages are left as they were in the dark theme (B-029 touches only the classic editor)", async ({ page }) => {
    await page.context().addCookies([{ name: "smartdoc_theme", value: "dark", url: "http://localhost:3100" }]);
    const id = await openDocument(page);
    await page.goto(`/documents/${id}?editor=2`);
    await expect(editor(page)).toBeVisible();
    await expect(page.locator(".paged-editor")).toHaveClass(/\bpaper\b/);
    await expect(page.locator(".paged-editor")).not.toHaveClass(/\bclassic\b/);
    await expect(editor(page).locator("p").filter({ hasText: "The first quarter" })).toHaveCSS("color", "rgb(15, 23, 42)");
  });
});
