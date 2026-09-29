import path from "node:path";

import { expect, test } from "@playwright/test";

import { createDocument, GOLDEN, signUp } from "./helpers";

/**
 * A Word file with several sections: each page shows its own section's header,
 * footer and page number, as Word does (tracker DOCX-015, brief §24) -- not the
 * last section's on every page. The pages here come from the editor's own layout,
 * which says where each section's pages begin.
 */

test("each page shows its own section's header, footer and number", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { file: path.join(GOLDEN, "14-section-headers.docx") });

  const part = (number: number, name: "header" | "footer") => page.locator(`[data-page="${number}"] [data-part="${name}"]`);
  await expect(page.locator("[data-page]")).toHaveCount(4);

  await expect(part(2, "header")).toHaveText("Front matter"); // the front matter, numbered i, ii..
  await expect(part(2, "footer")).toHaveText("Page ii");
  await expect(part(1, "header")).toHaveCount(0); // its cover: an empty header of its own, no first-page footer
  await expect(part(1, "footer")).toHaveCount(0);
  await expect(part(3, "header")).toHaveText("Chapter one"); // a chapter with its own header, numbered from 1
  await expect(part(3, "footer")).toHaveText("Page 1"); // the footer linked to the front matter's
  await expect(part(4, "header")).toHaveText("Chapter one"); // the last section, linked to the chapter's
  await expect(part(4, "footer")).toHaveText("Page 2");
});
