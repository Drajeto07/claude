import path from "node:path";

import { expect, test } from "@playwright/test";

import { API, createDocument, editor, GOLDEN, signUp, unzipped } from "./helpers";

/**
 * Word's hidden text stays hidden (tracker DOCX-025): the pages don't show it
 * until asked, "Show hidden text" shows it with Word's dotted line, and the Word
 * export keeps it hidden.
 */

test("Word's hidden text stays hidden, and shows on request", async ({ page }) => {
  await signUp(page);
  const id = await createDocument(page, { file: path.join(GOLDEN, "02-rich-text.docx") });

  await expect(editor(page).getByText("A second, ordinary paragraph.")).toBeVisible();
  const note = editor(page).locator(".hidden-text", { hasText: "A note only its author sees." });
  await expect(note).toHaveCount(1);
  await expect(note).toBeHidden();

  await page.getByRole("button", { name: "Show hidden text (6 words)" }).click();
  await expect(note).toBeVisible();
  await expect(note).toHaveCSS("border-bottom-style", "dotted");
  await page.getByRole("button", { name: "Hide hidden text" }).click();
  await expect(note).toBeHidden();

  const exported = await page.request.get(`${API}/documents/${id}/export/docx`);
  expect(exported.ok()).toBeTruthy();
  const body = unzipped(await exported.body(), "word/document.xml");
  expect(body).toMatch(/<w:vanish\/><\/w:rPr><w:t[^>]*> A note only its author sees\.<\/w:t>/);
});
