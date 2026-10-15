import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { createDocument, editor, GOLDEN, signUp } from "./helpers";

/**
 * D-012 user test (2026-10-15): "This document was changed in another tab or window" while one person typed in one
 * tab. Typing in bursts around the autosave delay, after an upload with a picture and a template, then a reload and
 * more typing, must never be called a conflict -- in either editor. A real conflict (a second tab) still must be.
 */

const CHANGED_ELSEWHERE = /changed in another tab or window/;

async function typeBursts(page: Page, words: string[], pauses: number[]) {
  const target = editor(page).locator("p").filter({ hasText: /\S/ }).first();
  await target.click();
  await page.keyboard.press("End");
  for (const [index, word] of words.entries()) {
    await page.keyboard.type(` ${word}`, { delay: 15 });
    await page.waitForTimeout(pauses[index % pauses.length]);
  }
}

async function noConflictAndSaved(page: Page) {
  await expect(page.getByText(CHANGED_ELSEWHERE)).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: /^Saved$/ }).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(CHANGED_ELSEWHERE)).toHaveCount(0);
}

/**
 * What Vercel's edge did (B-027, from the Preview's logs: the app answered a save 200, the browser got 412): a
 * request carrying If-Match whose answer succeeded is answered 412 Precondition Failed instead. The client must not
 * depend on If-Match reaching the app untouched.
 */
async function behindAnEdgeThatEvaluatesIfMatch(page: Page) {
  const seen = { withIfMatch: 0, revisionHeader: 0 };
  await page.route("**/api/v1/documents/*/content", async (route) => {
    const headers = route.request().headers();
    if (headers["x-smartdoc-revision"]) seen.revisionHeader += 1;
    const response = await route.fetch();
    if (headers["if-match"] !== undefined) {
      seen.withIfMatch += 1;
      if (response.ok()) {
        await route.fulfill({ status: 412, contentType: "text/plain", body: "Precondition Failed" });
        return;
      }
    }
    await route.fulfill({ response });
  });
  return seen;
}

for (const shell of ["classic", "v2"] as const) {
  test.describe(`${shell} editor behind an edge that evaluates If-Match`, () => {
    test.beforeEach(async ({ page }) => {
      await signUp(page);
    });

    test("saves go through and are never called a conflict", async ({ page }) => {
      const id = await createDocument(page, { text: "# Edge\n\nFirst paragraph of the document behind the edge." });
      const seen = await behindAnEdgeThatEvaluatesIfMatch(page);
      await page.goto(shell === "v2" ? `/documents/${id}?editor=2` : `/documents/${id}`);
      await expect(editor(page)).toBeVisible();

      await typeBursts(page, ["one", "two", "three", "four"], [1500, 1600, 1500, 1700]);
      await noConflictAndSaved(page);
      await page.reload();
      await expect(editor(page).getByText(/four/)).toBeVisible();
      expect(seen.withIfMatch).toBe(0);
      expect(seen.revisionHeader).toBeGreaterThan(0);
    });
  });
}

for (const shell of ["classic", "v2"] as const) {
  test.describe(`${shell} editor`, () => {
    test.beforeEach(async ({ page }) => {
      await signUp(page);
    });

    test("one person typing in bursts after an upload with a picture and a template is never a conflict", async ({ page }) => {
      const id = await createDocument(page, { file: path.join(GOLDEN, "17-pictures.docx") }, { template: "Академичен" });
      if (shell === "v2") await page.goto(`/documents/${id}?editor=2`);
      await expect(editor(page)).toBeVisible();

      // Pauses below, around and above the autosave delay (1.2 s): saves overlap typing and each other.
      await typeBursts(page, ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"], [300, 1250, 1600, 50, 2500]);
      await noConflictAndSaved(page);

      await page.reload();
      await expect(editor(page).getByText(/zeta/)).toBeVisible();
      await typeBursts(page, ["eta", "theta", "iota"], [1300, 200, 1700]);
      await noConflictAndSaved(page);

      await page.reload();
      await expect(editor(page).getByText(/iota/)).toBeVisible();
      await expect(editor(page).locator("img").first()).toBeVisible();
    });

    test("a real change from a second tab is still a conflict, and nothing is overwritten", async ({ page, context }) => {
      const id = await createDocument(page, { text: "# Shared\n\nFirst paragraph of the shared document." });
      if (shell === "v2") await page.goto(`/documents/${id}?editor=2`);
      await expect(editor(page)).toBeVisible();

      const second = await context.newPage();
      await second.goto(shell === "v2" ? `/documents/${id}?editor=2` : `/documents/${id}`);
      await expect(editor(second)).toBeVisible();
      await typeBursts(second, ["from-the-second-tab"], [10]);
      await noConflictAndSaved(second);

      await typeBursts(page, ["from-the-first-tab"], [10]);
      await expect(page.getByText(CHANGED_ELSEWHERE).first()).toBeVisible({ timeout: 20_000 });
      await second.reload();
      await expect(editor(second).getByText(/from-the-second-tab/)).toBeVisible();
      await expect(editor(second).getByText(/from-the-first-tab/)).toHaveCount(0);
    });
  });
}
