import { expect, test, type Page } from "@playwright/test";

import { createDocument, editor, isContentSave, signUp } from "./helpers";

/**
 * Pasting rich content -- lists and code inside table cells, a list inside a quote,
 * code inside a list item, a numbered list starting at 3 in letters -- is saved
 * and still there, all of it, after a reload (tracker EDIT-006). Before the fix
 * the editor said "Saved" and dropped every one of these on the way to the server.
 */

const PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

const PASTED = `
  <table>
    <tr><th><p>Step</p></th><th><p>How</p></th></tr>
    <tr>
      <td><p>Install</p></td>
      <td><p>Run these:</p><ul><li><p>fetch the code</p></li><li><p>install packages</p></li></ul><pre><code>npm ci</code></pre></td>
    </tr>
    <tr><td><p>Check</p></td><td><img src="${PNG}" alt="Result chart"><p>Figure 1</p></td></tr>
  </table>
  <blockquote><p>Remember:</p><ul><li><p>back up first</p></li></ul></blockquote>
  <ul><li><p>Build it</p><pre><code>make release</code></pre></li></ul>
  <ol start="3" type="a"><li><p>third point</p></li><li><p>fourth point</p></li></ol>`;

async function paste(page: Page, html: string) {
  await editor(page).evaluate((element, markup) => {
    const data = new DataTransfer();
    data.setData("text/html", markup);
    data.setData("text/plain", "pasted");
    element.dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true }));
  }, html);
}

async function expectEverythingThere(page: Page) {
  const content = editor(page);
  await expect(content.getByRole("heading", { name: "Runbook", exact: true })).toBeVisible();
  await expect(content.locator("td li")).toHaveText(["fetch the code", "install packages"]);
  await expect(content.locator("td pre")).toHaveText("npm ci");
  await expect(content.locator('td img[alt="Result chart"]')).toHaveCount(1);
  await expect(content.locator("td").filter({ hasText: "Figure 1" })).toHaveCount(1);
  await expect(content.locator("blockquote li")).toHaveText("back up first");
  await expect(content.locator("blockquote")).toContainText("Remember:");
  await expect(content.locator("li pre")).toHaveText("make release");
  const lettered = content.locator('ol[start="3"]');
  await expect(lettered).toHaveAttribute("type", "a");
  await expect(lettered.locator("li")).toHaveText(["third point", "fourth point"]);
}

test("pasted lists, code and pictures inside cells, quotes and list items survive a reload", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { text: "# Runbook\n\nThe steps below." });

  // Paste into a new paragraph at the very end, with the editor surely focused
  // (a click in the first moments after loading can leave the caret at the start).
  await editor(page).getByText("The steps below.").click();
  await expect(editor(page)).toBeFocused();
  await page.keyboard.press("Control+End");
  await page.keyboard.press("Enter");
  const saved = page.waitForResponse(isContentSave);
  await paste(page, PASTED);
  await saved;
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  await expectEverythingThere(page);
  await expect(page.getByText(/Not saved/)).toHaveCount(0);

  await page.reload();
  await expect(editor(page).getByText("The steps below.")).toBeVisible();
  await expectEverythingThere(page);
});
