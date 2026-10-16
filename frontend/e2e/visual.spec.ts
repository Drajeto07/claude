import path from "node:path";

import { expect, test } from "@playwright/test";

import { GOLDEN, createDocument, signUp } from "./helpers";

/**
 * Visual regression for the editor (корекции.docx §43): a Word document with
 * everything in it, formatted with a template, must look the same as the
 * approved screenshot -- pages, headings, lists, table, picture, captions.
 * Screenshots depend on the system's fonts and the browser's text rendering, so the
 * baseline is Windows' in Chromium; run with --update-snapshots after an intended
 * change to the editor's look.
 */
test.skip(process.platform !== "win32", "The baseline screenshot is of Windows' fonts");
test.skip(({ browserName }) => browserName !== "chromium", "The baseline screenshot is Chromium's text rendering");
// Tall enough for a whole page above the editor's bottom bars (the zoom follows the width).
test.use({ viewport: { width: 1400, height: 1600 } });

test("the editor draws a formatted document as approved", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { file: path.join(GOLDEN, "12-complex.docx") }, { template: "Академичен" });
  const picture = page.locator(".paged-editor img");
  await expect.poll(() => picture.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true);
  const firstPage = page.locator('.paged-editor > div[aria-hidden="true"]').first();

  await expect(firstPage).toHaveScreenshot("editor-complex-academic.png", {
    animations: "disabled",
    caret: "hide",
    maxDiffPixelRatio: 0.01,
  });
});
