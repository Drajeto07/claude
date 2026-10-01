import { expect, test, type Page } from "@playwright/test";

import { createDocument, editor, isContentSave, signUp } from "./helpers";

/**
 * Formatting pasted onto blocks themselves -- a centred line, a picture's size --
 * is saved as those elements' own style and is still there after a reload
 * (tracker EDIT-008, EDIT-009); what the document can't keep (a colour in hsl())
 * is named in the status bar instead of vanishing without a word (EDIT-012).
 */

const PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

const PASTED = `
  <p style="text-align: center">A centred line</p>
  <img src="${PNG}" alt="Logo" width="321">
  <p><span style="color: hsl(0, 100%, 50%)">Red in hsl</span></p>`;

async function paste(page: Page, html: string) {
  await editor(page).evaluate((element, markup) => {
    const data = new DataTransfer();
    data.setData("text/html", markup);
    data.setData("text/plain", "pasted");
    element.dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true }));
  }, html);
}

test("pasted alignment and picture size survive a reload, and what can't be kept is named", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { text: "# Notes\n\nThe first paragraph." });

  await editor(page).getByText("The first paragraph.").click();
  await expect(editor(page)).toBeFocused();
  await page.keyboard.press("Control+End");
  await page.keyboard.press("Enter");
  const saved = page.waitForResponse(
    (response) => isContentSave(response) && (response.request().postData() ?? "").includes('"styles":[{'),
  );
  await paste(page, PASTED);
  await saved;
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  // A4 with the default 2 cm margins: 321 px is half the text width.
  await expect(page.getByText("1 formatting change not kept")).toBeVisible();

  await page.reload();
  const centred = editor(page).getByText("A centred line");
  await expect(centred).toBeVisible();
  await expect(centred).toHaveCSS("text-align", "center");
  await expect(editor(page).getByText("The first paragraph.")).toHaveCSS("text-align", /left|start|justify/);
  const logo = editor(page).locator('img[alt="Logo"]');
  await expect(logo).toHaveCount(1);
  expect(await logo.evaluate((element) => (element as HTMLElement).style.width)).toBe("50%");
  await expect(editor(page).getByText("Red in hsl")).toBeVisible(); // the words stay; only the colour went
  await expect(page.getByText(/formatting changes? not kept/)).toHaveCount(0);
});
