import path from "node:path";

import { expect, test } from "@playwright/test";

import { createDocument, editor, GOLDEN, signUp } from "./helpers";

/**
 * A Word file with several sections: each page shows its own section's header,
 * footer and page number, as Word does (tracker DOCX-015, brief §24) -- not the
 * last section's on every page -- and has its section's size and margins. The
 * pages here come from the editor's own layout, which says which section each
 * page is in.
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

test("each section's pages have its own size, and its text its page's width", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { file: path.join(GOLDEN, "13-kept-blocks.docx") }); // a landscape section, then a portrait one

  const first = page.locator('[data-page="1"]');
  const second = page.locator('[data-page="2"]');
  await expect(page.locator("[data-page]")).toHaveCount(2);
  await expect.poll(async () => {
    const box = await first.boundingBox();
    return box !== null && box.width > box.height;
  }).toBe(true);
  const wide = (await first.boundingBox())!;
  const tall = (await second.boundingBox())!;
  expect(tall.width).toBeLessThan(tall.height);

  // Each section's text runs across its own page's column, inside that page.
  const landscape = (await editor(page).getByText("The results section.").boundingBox())!;
  const portrait = (await editor(page).getByText("Edit this line.").boundingBox())!;
  expect(landscape.width).toBeGreaterThan(portrait.width + 100);
  expect(landscape.x).toBeGreaterThan(wide.x);
  expect(landscape.x + landscape.width).toBeLessThan(wide.x + wide.width);
  expect(landscape.y + landscape.height).toBeLessThan(wide.y + wide.height);
  expect(portrait.x).toBeGreaterThan(tall.x);
  expect(portrait.x + portrait.width).toBeLessThan(tall.x + tall.width);
  expect(portrait.y).toBeGreaterThan(tall.y);
});
