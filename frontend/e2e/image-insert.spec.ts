import { expect, test, type Page } from "@playwright/test";

import { API, createDocument, editor, signUp, unzipped } from "./helpers";

/**
 * A picture from the person's own device put into a document (S2-130): picked with Add element -> Image, pasted
 * (Ctrl+V) or dropped onto the pages -- between the blocks, the text around it as it was -- then saved as the
 * workspace's own asset, back after a reload, in the DOCX and PDF exports, and private to its owner. A file that
 * isn't a picture, or is too large, is refused with a message, and a paste of text stays text.
 */

const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
const TEXT = "First paragraph of the report.\n\nSecond paragraph of the report.";

/** The status bar says everything is saved (the 2.0 shell shows it twice: its top bar and the page footer). */
async function waitUntilSaved(page: Page) {
  await expect(page.getByText("Saved", { exact: true }).first()).toBeVisible();
}

/** The editor's error message (Next.js keeps a route announcer with role alert too). */
function editorAlert(page: Page, text: string) {
  return page.getByRole("alert").filter({ hasText: text });
}

async function blocks(page: Page): Promise<string[]> {
  return editor(page).evaluate((root) => Array.from(root.children).map((child) => (child.tagName === "IMG" || child.querySelector("img") ? "img" : (child.textContent ?? "").trim())));
}

async function caretAtEndOf(page: Page, text: string) {
  await editor(page).getByText(text).click();
  await page.keyboard.press("End");
}

/** A paste of these files (and text, if given) into the focused editor, as the browser sends one. */
async function paste(page: Page, files: { name: string; type: string; base64: string }[], text = "") {
  await editor(page).evaluate(
    (root, { files, text }) => {
      const data = new DataTransfer();
      for (const one of files) data.items.add(new File([Uint8Array.from(atob(one.base64), (c) => c.charCodeAt(0))], one.name, { type: one.type }));
      if (text) data.setData("text/plain", text);
      root.dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true }));
    },
    { files, text },
  );
}

const picture = { name: "logo.png", type: "image/png", base64: PNG.toString("base64") };

test("a picture picked with Add element goes in after the paragraph, is saved as an asset, comes back and is exported", async ({ page, browser }) => {
  await signUp(page);
  const id = await createDocument(page, { text: TEXT });
  await caretAtEndOf(page, "First paragraph of the report.");

  // Reachable from the keyboard: the menu button, then its Image option, open the device's file dialog.
  await page.getByRole("button", { name: "Add element" }).focus();
  await page.keyboard.press("Enter");
  const image = page.getByRole("button", { name: "Image" });
  await expect(image).toBeEnabled();
  await image.focus();
  const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.keyboard.press("Enter")]);
  await chooser.setFiles({ name: "logo.png", mimeType: "image/png", buffer: PNG });

  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "img", "Second paragraph of the report."]);
  await waitUntilSaved(page);

  // Stored once as the workspace's asset: the document holds its id, no bytes.
  const stored = await (await page.request.get(`${API}/documents/${id}`)).json();
  const element = stored.elements.find((one: { type: string }) => one.type === "image");
  expect(element.image.assetId).toBeTruthy();
  expect(element.image.src).toBe("");
  const served = await page.request.get(`${API}/assets/${element.image.assetId}`);
  expect(served.status()).toBe(200);
  expect(served.headers()["content-type"]).toBe("image/png");

  await page.reload();
  await expect(editor(page).locator("img")).toHaveCount(1);
  await expect(editor(page).locator("img")).toHaveAttribute("src", new RegExp(`/api/v1/assets/${element.image.assetId}$`));
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "img", "Second paragraph of the report."]);

  const docx = Buffer.from(await (await page.request.get(`${API}/documents/${id}/export/docx`)).body());
  expect(unzipped(docx, "word/document.xml")).toContain("<w:drawing>");
  expect(unzipped(docx, "word/_rels/document.xml.rels")).toMatch(/Target="media\/[^"]+\.png"/);
  const pdf = Buffer.from(await (await page.request.get(`${API}/documents/${id}/export/pdf`)).body());
  expect(pdf.toString("latin1")).toMatch(/\/Subtype\s*\/Image/);

  // Private to its owner: another account gets nothing.
  const other = await browser.newContext();
  const stranger = await other.newPage();
  await signUp(stranger);
  expect((await stranger.request.get(`${API}/assets/${element.image.assetId}`)).status()).toBe(404);
  await other.close();
});

test("a pasted picture goes in after the caret's paragraph; a paste of text stays text", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { text: TEXT });
  await caretAtEndOf(page, "First paragraph of the report.");
  await paste(page, [picture]);
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "img", "Second paragraph of the report."]);
  // The caret stays in the text: typing goes on there and doesn't replace the picture.
  await page.keyboard.type(" (see below)");
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report. (see below)", "img", "Second paragraph of the report."]);
  await waitUntilSaved(page);

  await caretAtEndOf(page, "Second paragraph of the report.");
  await page.keyboard.type(" Typed");
  await paste(page, [], " and pasted");
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report. (see below)", "img", "Second paragraph of the report. Typed and pasted"]);
  // Undo takes back what was just typed and pasted (one group, as the editor groups quick edits); the picture and the
  // text before it stay.
  await page.keyboard.press("Control+z");
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report. (see below)", "img", "Second paragraph of the report."]);
});

test("text copied with a picture of itself (as from Word) is pasted as text", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { text: TEXT });
  await caretAtEndOf(page, "First paragraph of the report.");
  await paste(page, [picture], " from Word");
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report. from Word", "Second paragraph of the report."]);
});

test("a picture dropped on the upper half of a paragraph goes in before it", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { text: TEXT });
  const target = editor(page).getByText("Second paragraph of the report.");
  await target.evaluate((paragraph, file) => {
    const box = paragraph.getBoundingClientRect();
    const data = new DataTransfer();
    data.items.add(new File([Uint8Array.from(atob(file.base64), (c) => c.charCodeAt(0))], file.name, { type: file.type }));
    const at = { clientX: box.left + 4, clientY: box.top + 2, bubbles: true, cancelable: true, dataTransfer: data };
    paragraph.dispatchEvent(new DragEvent("dragover", at));
    paragraph.dispatchEvent(new DragEvent("drop", at));
  }, picture);
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "img", "Second paragraph of the report."]);
  await waitUntilSaved(page);
});

test("a file that isn't a picture, or is too large, is refused with a message and nothing goes in", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { text: TEXT });
  await caretAtEndOf(page, "First paragraph of the report.");

  await paste(page, [{ name: "fake.png", type: "image/png", base64: Buffer.from("not a picture at all").toString("base64") }]);
  await expect(editorAlert(page, "“fake.png” isn't a picture the document can take")).toBeVisible();

  await page.getByRole("button", { name: "Add element" }).click();
  const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.getByRole("button", { name: "Image" }).click()]);
  await chooser.setFiles({ name: "huge.png", mimeType: "image/png", buffer: Buffer.concat([PNG, Buffer.alloc(3 * 1024 * 1024)]) });
  await expect(editorAlert(page, "“huge.png” is too large")).toBeVisible();

  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "Second paragraph of the report."]);
});

test("the 2.0 editor takes a pasted picture the same way", async ({ page }) => {
  await signUp(page);
  const id = await createDocument(page, { text: TEXT });
  await page.goto(`/documents/${id}?editor=2`);
  await expect(editor(page)).toBeVisible();
  await caretAtEndOf(page, "First paragraph of the report.");
  await paste(page, [picture]);
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "img", "Second paragraph of the report."]);
  await waitUntilSaved(page);
  const stored = await (await page.request.get(`${API}/documents/${id}`)).json();
  expect(stored.elements.filter((one: { type: string; image?: { assetId: string } }) => one.type === "image" && one.image?.assetId)).toHaveLength(1);
});

/** A real PNG grown with bytes after its end (decoders ignore them) to exactly `size` bytes. */
function pngOfSize(size: number): Buffer {
  return Buffer.concat([PNG, Buffer.alloc(size - PNG.length)]);
}

function isSave(url: string, method: string) {
  return url.endsWith("/content") && ["PATCH", "PUT"].includes(method);
}

test("up to 3 MB is taken and saved; a byte more is refused before anything is sent", async ({ page }) => {
  test.setTimeout(90_000);
  await signUp(page);
  const id = await createDocument(page, { text: TEXT });
  await caretAtEndOf(page, "First paragraph of the report.");
  const saves: number[] = [];
  page.on("request", (request) => {
    // Only the saves that carry a picture (the editor may save other things meanwhile).
    if (isSave(request.url(), request.method()) && (request.postData() ?? "").includes("data:image/")) saves.push(request.postDataBuffer()?.length ?? 0);
  });

  await page.getByRole("button", { name: "Add element" }).click();
  let [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.getByRole("button", { name: "Image" }).click()]);
  await chooser.setFiles({ name: "over.png", mimeType: "image/png", buffer: pngOfSize(3 * 1024 * 1024 + 1) });
  await expect(editorAlert(page, "“over.png” is too large: a picture can take up to 3 MB")).toBeVisible();
  expect(saves).toEqual([]);

  await page.getByRole("button", { name: "Add element" }).click();
  [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.getByRole("button", { name: "Image" }).click()]);
  await chooser.setFiles({ name: "limit.png", mimeType: "image/png", buffer: pngOfSize(3 * 1024 * 1024) });
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "img", "Second paragraph of the report."]);
  await waitUntilSaved(page);
  // The one save that carried it stays under the hosting's 4.5 MB request limit.
  expect(saves.length).toBeGreaterThan(0);
  expect(Math.max(...saves)).toBeLessThan(4_500_000);
  const stored = await (await page.request.get(`${API}/documents/${id}`)).json();
  expect(stored.elements.find((one: { type: string }) => one.type === "image").image.assetId).toBeTruthy();
});

test("two pictures picked at once go in in order, each in a save of its own", async ({ page }) => {
  await signUp(page);
  const id = await createDocument(page, { text: TEXT });
  await caretAtEndOf(page, "First paragraph of the report.");
  const carried: number[] = [];
  page.on("request", (request) => {
    if (isSave(request.url(), request.method())) carried.push(((request.postData() ?? "").match(/data:image\//g) ?? []).length);
  });
  await page.getByRole("button", { name: "Add element" }).click();
  const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.getByRole("button", { name: "Image" }).click()]);
  await chooser.setFiles([
    { name: "one.png", mimeType: "image/png", buffer: PNG },
    { name: "two.png", mimeType: "image/png", buffer: pngOfSize(PNG.length + 10) },
  ]);
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "img", "img", "Second paragraph of the report."]);
  await waitUntilSaved(page);
  expect(carried.filter((count) => count > 0)).toEqual([1, 1]);
  const stored = await (await page.request.get(`${API}/documents/${id}`)).json();
  expect(stored.elements.filter((one: { type: string; image?: { assetId: string } }) => one.type === "image" && one.image?.assetId)).toHaveLength(2);
});

test("a picture's save refused as too large (the hosting's 413) is never shown as saved; undoing it lets saving go on", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { text: TEXT });
  await caretAtEndOf(page, "First paragraph of the report.");
  // As Vercel answers a request over 4.5 MB: before the app, in plain text.
  await page.route("**/content", (route) =>
    (route.request().postData() ?? "").includes("data:image/")
      ? route.fulfill({ status: 413, contentType: "text/plain", body: "Request Entity Too Large\n\nFUNCTION_PAYLOAD_TOO_LARGE" })
      : route.continue(),
  );
  await paste(page, [picture]);
  await expect(editorAlert(page, "The picture couldn't be saved, so the document isn't being saved either.")).toBeVisible();
  await expect(page.getByText(/^Not saved/).first()).toBeVisible();
  await expect(page.getByText("Saved", { exact: true })).toHaveCount(0);

  await page.keyboard.press("Control+z");
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "Second paragraph of the report."]);
  await page.keyboard.type(" Still here.");
  await waitUntilSaved(page);
});

test.describe("on a phone", () => {
  test.use({ hasTouch: true });

  for (const width of [375, 390]) {
    test(`at ${width} px, both editors offer a picture from the phone, without sideways scrolling`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await signUp(page);
      const id = await createDocument(page, { text: TEXT });

      // The classic editor: Add element -> Image, in the bar under the writing view.
      await page.getByRole("button", { name: "Add element" }).tap();
      let [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.getByRole("button", { name: "Image" }).tap()]);
      await chooser.setFiles({ name: "photo.png", mimeType: "image/png", buffer: PNG });
      await expect(editor(page).locator("img")).toHaveCount(1);
      await waitUntilSaved(page);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBe(0);

      // The 2.0 editor: its phone bar's Insert image button.
      await page.goto(`/documents/${id}?editor=2`);
      await expect(editor(page).locator("img")).toHaveCount(1);
      const insert = page.getByRole("button", { name: "Insert image" });
      await expect(insert).toBeVisible();
      const box = (await insert.boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(width);
      [chooser] = await Promise.all([page.waitForEvent("filechooser"), insert.tap()]);
      await chooser.setFiles({ name: "second.png", mimeType: "image/png", buffer: PNG });
      await expect(editor(page).locator("img")).toHaveCount(2);
      await waitUntilSaved(page);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBe(0);
      const stored = await (await page.request.get(`${API}/documents/${id}`)).json();
      expect(stored.elements.filter((one: { type: string; image?: { assetId: string } }) => one.type === "image" && one.image?.assetId)).toHaveLength(2);
    });
  }
});

test("on a wide screen the 2.0 editor offers pictures through Add element, not the phone button", async ({ page }) => {
  await signUp(page);
  const id = await createDocument(page, { text: TEXT });
  await page.goto(`/documents/${id}?editor=2`);
  await expect(editor(page)).toBeVisible();
  await expect(page.getByRole("button", { name: "Insert image" })).toBeHidden();
  await page.getByRole("button", { name: "Add element" }).click();
  await expect(page.getByRole("button", { name: "Image" })).toBeEnabled();
});
