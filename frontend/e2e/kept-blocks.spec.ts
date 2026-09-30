import path from "node:path";

import { expect, test } from "@playwright/test";

import { API, createDocument, editor, GOLDEN, signUp, unzipped, waitUntilSaved } from "./helpers";

/**
 * A Word file edited in the app keeps, in the paragraphs nobody touched, what the
 * app doesn't show -- a content control, a landscape section
 * (tracker DOCX-028). The Word export copies a block as it is only while the
 * editor has given it back exactly as it was imported, so this is the editor's
 * round trip checked against the server's fingerprints.
 */

test("a Word file's untouched paragraphs keep what the app doesn't show", async ({ page }) => {
  await signUp(page);
  const id = await createDocument(page, { file: path.join(GOLDEN, "13-kept-blocks.docx") });

  await editor(page).getByText("Edit this line.").click();
  await page.keyboard.press("End");
  const saved = page.waitForResponse(
    (response) =>
      response.url().endsWith("/content") &&
      response.request().method() === "PUT" &&
      response.ok() &&
      (response.request().postData() ?? "").includes("Changed in the app."),
  );
  await page.keyboard.type(" Changed in the app.");
  await saved;
  await waitUntilSaved(page);

  const exported = await page.request.get(`${API}/documents/${id}/export/docx`);
  expect(exported.ok()).toBeTruthy();
  const body = unzipped(await exported.body(), "word/document.xml");

  expect(body).toContain("Edit this line. Changed in the app."); // the edited paragraph, written anew
  expect(body).toContain('<w:alias w:val="Status"/>'); // the content control, which only a copy keeps
  expect(body).toContain('<w:u w:val="double"/>'); // the double underline (the model holds it too since DOCX-013)
  expect(body).toContain("AUTHOR"); // the field's code
  expect(body.match(/<w:sectPr/g)).toHaveLength(2); // the landscape section before the portrait one
  expect(body).toContain('w:orient="landscape"');
});

test("a paragraph deleted in the editor stays deleted in the Word export", async ({ page }) => {
  // Before DOCX-028B the export copied a deleted block's original with the one before it.
  await signUp(page);
  const id = await createDocument(page, { file: path.join(GOLDEN, "13-kept-blocks.docx") });

  await editor(page).getByText("Underlined twice").click();
  await page.keyboard.press("End");
  await page.keyboard.press("Shift+Home");
  await page.keyboard.press("Backspace"); // its text
  await page.keyboard.press("Backspace"); // and the paragraph

  await expect // saved without it: the element itself gone, not left empty
    .poll(
      async () => {
        const stored = await (await page.request.get(`${API}/documents/${id}`)).json();
        return stored.elements
          .filter((element: { type: string }) => element.type === "paragraph")
          .map((element: { content: string }) => element.content);
      },
      { timeout: 15_000 },
    )
    .toEqual(["Written by SmartDoc golden fixtures", "Draft for review", "The results section.", "Edit this line."]);
  await waitUntilSaved(page);
  const exported = await page.request.get(`${API}/documents/${id}/export/docx`);
  expect(exported.ok()).toBeTruthy();
  const body = unzipped(await exported.body(), "word/document.xml");

  expect(body).not.toContain("Underlined");
  expect(body).toContain('<w:alias w:val="Status"/>'); // the untouched blocks still copied as they were
  expect(body).toContain("AUTHOR");
});
