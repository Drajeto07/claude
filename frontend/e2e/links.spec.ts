import path from "node:path";

import { expect, test } from "@playwright/test";

import { createDocument, editor, GOLDEN, signUp } from "./helpers";

/**
 * A Word file's plain-text addresses stay text, as its author left them, unless the
 * person asks for links when uploading it (tracker DOCX-026); its real links are links.
 */

test("plain addresses stay text unless links are asked for", async ({ page }) => {
  await signUp(page);
  const file = path.join(GOLDEN, "05-links.docx");

  await createDocument(page, { file });
  await expect(editor(page).getByText("A plain address stays text: www.example.net.")).toBeVisible();
  await expect(editor(page).locator("a", { hasText: "www.example.net" })).toHaveCount(0);
  await expect(editor(page).locator("a", { hasText: "the documentation" })).toHaveAttribute("href", "https://example.com/docs");

  await createDocument(page, { file }, { autolink: true });
  await expect(editor(page).locator("a", { hasText: "www.example.net" })).toHaveAttribute("href", "https://www.example.net");
});
