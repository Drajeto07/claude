import { expect, test, type Page } from "@playwright/test";

import { API, createDocument, editor, signUp } from "./helpers";

/**
 * B-038: the save status after changes that end where the save is. An undo and a redo inside one autosave pause, or
 * an undo while a save is on its way, left "Not saved yet" for good although the editor held exactly what the server
 * had (nothing more was sent, nothing ever said saved). Now it says Saved -- and only when that is so: the reload shows
 * what the editor showed.
 */

const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");

const status = (page: Page) => page.getByRole("status").filter({ hasText: /^(Saved|Saving…|Not saved yet|Failed to save.*)$/ }).first();

async function blocks(page: Page) {
  return editor(page).evaluate((root) =>
    Array.from(root.children)
      .filter((child) => !child.classList.contains("ProseMirror-widget"))
      .map((child) => (child.querySelector("img") || child.tagName === "IMG" ? "img" : (child.textContent ?? "").trim())),
  );
}

test("typing, then undo and redo at once: it says Saved, and the reload shows the same text", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { text: "First paragraph of the report.\n\nSecond paragraph of the report." });
  await editor(page).getByText("Second paragraph of the report.").click();
  await page.keyboard.press("End");
  await page.keyboard.type(" Added.");
  await expect(status(page)).toHaveText("Saved");
  await page.keyboard.press("Control+z");
  await page.keyboard.press("Control+y");
  await expect(status(page)).toHaveText("Saved"); // was "Not saved yet" for good
  const shown = await blocks(page);
  await page.reload();
  await expect.poll(() => blocks(page)).toEqual(shown);
  expect(shown).toEqual(["First paragraph of the report.", "Second paragraph of the report. Added."]);
});

test("a picture undone while its save is on its way and redone: it says Saved, and the picture is there after a reload", async ({ page }) => {
  await signUp(page);
  const id = await createDocument(page, { text: "First paragraph of the report.\n\nSecond paragraph of the report." });
  await editor(page).getByText("First paragraph of the report.").click();
  await page.keyboard.press("End");
  await page.getByRole("button", { name: "Add element" }).click();
  const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.getByRole("button", { name: "Image" }).click()]);
  await chooser.setFiles({ name: "a.png", mimeType: "image/png", buffer: PNG });
  await expect(editor(page).locator("img")).toHaveCount(1);
  await editor(page).getByText("Second paragraph of the report.").click();
  await page.keyboard.press("Control+z");
  await expect(editor(page).locator("img")).toHaveCount(0);
  await page.keyboard.press("Control+y");
  await expect(editor(page).locator("img")).toHaveCount(1);
  await expect(status(page)).toHaveText("Saved");
  const stored = await (await page.request.get(`${API}/documents/${id}`)).json();
  expect(stored.elements.map((one: { type: string }) => one.type)).toEqual(["paragraph", "image", "paragraph"]);
  await page.reload();
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "img", "Second paragraph of the report."]);
});

test("an undo that is a real change is saved before it says Saved", async ({ page }) => {
  await signUp(page);
  const id = await createDocument(page, { text: "First paragraph of the report." });
  await editor(page).getByText("First paragraph of the report.").click();
  await page.keyboard.press("End");
  await page.keyboard.type(" More.");
  await expect(status(page)).toHaveText("Saved");
  const undoSaved = page.waitForResponse((response) => /\/content$/.test(response.url()) && ["PATCH", "PUT"].includes(response.request().method()));
  await page.keyboard.press("Control+z");
  expect((await undoSaved).ok()).toBe(true);
  await expect(status(page)).toHaveText("Saved");
  const stored = await (await page.request.get(`${API}/documents/${id}`)).json();
  expect(stored.elements.map((one: { content: string }) => one.content)).toEqual(["First paragraph of the report."]);
});

test("the 2.0 editor: typing, then undo and redo at once: it says Saved, and the reload shows the same text", async ({ page }) => {
  await signUp(page);
  const id = await createDocument(page, { text: "First paragraph of the report.\n\nSecond paragraph of the report." });
  await page.goto(`/documents/${id}?editor=2`);
  await editor(page).getByText("Second paragraph of the report.").click();
  await page.keyboard.press("End");
  await page.keyboard.type(" Added.");
  await expect(status(page)).toHaveText("Saved");
  await page.keyboard.press("Control+z");
  await page.keyboard.press("Control+y");
  await expect(status(page)).toHaveText("Saved");
  await page.reload();
  await expect.poll(() => blocks(page)).toEqual(["First paragraph of the report.", "Second paragraph of the report. Added."]);
});
