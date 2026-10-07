import { expect, test } from "@playwright/test";

import { API, createDocument, signUp } from "./helpers";

/**
 * Batch formatting, export and translation (tracker FEAT-001, FEAT-002, FEAT-003): documents ticked
 * in the list get one template at once, as a batch of format jobs followed until each is done, go
 * into one ZIP, and are translated into one language -- a new document each, the originals as they were.
 */
test("one template is applied to the documents ticked in the list, then they go into one ZIP", async ({ page }) => {
  await signUp(page);
  const first = await createDocument(page, { text: "# Batch one\n\nThe first report." });
  const second = await createDocument(page, { text: "# Batch two\n\nThe second report." });

  await page.goto("/documents");
  await page.getByRole("checkbox", { name: /^Select .*one/ }).check();
  await page.getByRole("checkbox", { name: /^Select .*two/ }).check();
  const bar = page.getByRole("region", { name: "Selected documents" });
  await expect(bar.getByText("2 selected")).toBeVisible();
  await bar.getByLabel("Template").selectOption("academic-default");
  await bar.getByRole("button", { name: "Apply to 2 documents" }).click();
  await expect(bar.getByRole("status")).toContainText("2 of 2 done");

  for (const id of [first, second]) {
    const document = await (await page.request.get(`${API}/documents/${id}`)).json();
    expect(document.templateId).toBe("academic-default");
  }
  await expect(page.getByText("Formatted", { exact: false }).first()).toBeVisible(); // the list's status, refreshed

  // Both into one ZIP (FEAT-002), downloaded like any export.
  await bar.getByLabel("Export format").selectOption("pdf");
  await bar.getByRole("button", { name: "Export as ZIP" }).click();
  const link = bar.getByRole("link", { name: /\.zip/ });
  await expect(link).toBeVisible();
  await expect(bar.getByText(/2 files; each holding every word of its document/)).toBeVisible();
  const zip = await page.request.get(new URL((await link.getAttribute("href"))!, page.url()).toString());
  expect(zip.ok()).toBeTruthy();
  expect(zip.headers()["content-type"]).toBe("application/zip");

  // Both translated into Bulgarian (FEAT-003): a new document each, linked from the bar.
  const before = await (await page.request.get(`${API}/documents/${first}`)).json();
  await bar.getByLabel("Translate into").selectOption("bg");
  await bar.getByRole("button", { name: "Translate 2 documents" }).click();
  await expect(bar.getByRole("status")).toContainText("2 of 2 translated into Bulgarian");
  const translationLink = bar.getByRole("link", { name: "translation 1" });
  await expect(translationLink).toBeVisible();
  const translated = await (await page.request.get(`${API}/documents/${(await translationLink.getAttribute("href"))!.split("/").pop()}`)).json();
  expect(translated.metadata.translatedFrom.documentId).toBe(first);
  expect(translated.metadata.language).toBe("bg");
  expect((await (await page.request.get(`${API}/documents/${first}`)).json()).elements).toEqual(before.elements); // the original as it was
});
