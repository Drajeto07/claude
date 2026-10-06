import path from "node:path";

import { expect, test } from "@playwright/test";

import {
  API,
  GOLDEN,
  PNG_DATA_URL,
  caretAtEndOf,
  createDocument,
  downloadExport,
  editor,
  isContentSave,
  makePdf,
  pasteHtml,
  signUp,
  toggleToolbar,
  toolbarButton,
  unzipped,
  waitUntilSaved,
  zipNames,
} from "./helpers";

/**
 * The brief's browser workflows (section 79) that no other spec walks end to end:
 * each test is one person's path through the real app, with its own account and
 * documents. docs/testing/README.md maps all 24 workflows to their specs.
 */

test.beforeEach(async ({ page }) => {
  await signUp(page);
});

test("structure review: the outline shows the headings found, nested, and folds", async ({ page }) => {
  const text = "# Handbook\n\nIntro.\n\n## Setup\n\nSteps.\n\n### Tools\n\nWhat to bring.\n\n## Usage\n\nHow it goes.";
  await createDocument(page, { text }, {
    onReview: async () => {
      await expect(page.getByText("4 headings, 4 paragraphs.", { exact: false })).toBeVisible();
      for (const heading of ["Handbook", "Setup", "Tools", "Usage"]) {
        await expect(page.getByRole("button", { name: heading, exact: true })).toBeVisible();
      }
      // The outline folds: Handbook's whole branch goes and comes back.
      await page.getByRole("button", { name: "Collapse" }).first().click();
      await expect(page.getByRole("button", { name: "Setup", exact: true })).toHaveCount(0);
      await page.getByRole("button", { name: "Expand" }).click();
      await expect(page.getByRole("button", { name: "Tools", exact: true })).toBeVisible();
    },
  });

  await expect(editor(page).getByRole("heading", { name: "Tools" })).toBeVisible();
});

test("paste: Markdown text becomes lists, a table and a link, which stay after a reload and reach the Word file", async ({ page }) => {
  const text = [
    "# Notes",
    "",
    "- first item",
    "- second item",
    "",
    "1. step one",
    "2. step two",
    "",
    "| Name | Qty |",
    "| --- | --- |",
    "| Pens | 12 |",
    "",
    "See [the docs](https://example.com/docs).",
  ].join("\n");
  await createDocument(page, { text });

  async function expectEverythingThere() {
    const content = editor(page);
    await expect(content.locator("ul li")).toHaveText(["first item", "second item"]);
    await expect(content.locator("ol li")).toHaveText(["step one", "step two"]);
    await expect(content.getByRole("cell", { name: "Pens" })).toBeVisible();
    await expect(content.getByRole("cell", { name: "12" })).toBeVisible();
    await expect(content.locator('a[href="https://example.com/docs"]')).toHaveText("the docs");
  }
  await expectEverythingThere();
  await page.reload();
  await expectEverythingThere();

  const file = await downloadExport(page, "DOCX");
  const body = unzipped(file.bytes, "word/document.xml");
  expect(body).toContain("<w:tbl>");
  expect(body).toContain("<w:hyperlink");
  expect(body.match(/<w:numPr>/g)?.length).toBeGreaterThanOrEqual(4); // each list item is numbered or bulleted
  expect(unzipped(file.bytes, "word/_rels/document.xml.rels")).toContain("https://example.com/docs");
});

test("manual edit: bold, a bullet list and a table added by hand are saved and exported", async ({ page }) => {
  await createDocument(page, { text: "# Notes\n\nPlain line." });

  // A line typed in bold, by the toolbar's button.
  await caretAtEndOf(page, "Plain line.");
  await page.keyboard.press("Enter");
  await toggleToolbar(page, "Bold", true);
  await page.keyboard.type("Strong line.");
  await expect(editor(page).locator("strong", { hasText: "Strong line." })).toBeVisible();
  await toggleToolbar(page, "Bold", false);

  // A bullet list typed after it.
  await page.keyboard.press("Enter");
  await toggleToolbar(page, "Bullet list", true);
  await page.keyboard.type("milk");
  await page.keyboard.press("Enter");
  await page.keyboard.type("eggs");
  await waitUntilSaved(page);

  // A table from the "add element" menu, then a word typed into its first cell.
  await page.getByRole("button", { name: "Добави елемент" }).click();
  await page.getByRole("button", { name: "Table", exact: true }).click();
  await expect(editor(page).locator("table")).toHaveCount(1);
  await editor(page).locator("td, th").first().click();
  await page.keyboard.type("Quantity");
  await waitUntilSaved(page);

  async function expectEverythingThere() {
    await expect(editor(page).getByText("Plain line.", { exact: true })).toBeVisible();
    await expect(editor(page).locator("strong", { hasText: "Strong line." })).toBeVisible();
    await expect(editor(page).locator("ul li")).toHaveText(["milk", "eggs"]);
    await expect(editor(page).locator("table")).toHaveCount(1);
    await expect(editor(page).getByRole("cell", { name: "Quantity" })).toBeVisible();
  }
  await expectEverythingThere();
  await page.reload();
  await expectEverythingThere();

  const body = unzipped((await downloadExport(page, "DOCX")).bytes, "word/document.xml");
  for (const word of ["Plain line.", "Strong line.", "milk", "eggs", "Quantity"]) expect(body).toContain(word);
  expect(body).toContain("<w:b/>");
  expect(body).toContain("<w:tbl>");
});

test("undo and redo of typing: the toolbar buttons and the keys, and the server holds what is left", async ({ page }) => {
  const id = await createDocument(page, { text: "# Plan\n\nFirst line." });
  const saved = async () => {
    const response = await page.request.get(`${API}/documents/${id}`);
    return ((await response.json()).elements as { content: string }[]).map((element) => element.content);
  };

  await caretAtEndOf(page, "First line.");
  await page.keyboard.type(" Second part.");
  await expect(editor(page).getByText("First line. Second part.")).toBeVisible();
  await waitUntilSaved(page);

  await toolbarButton(page, "Undo").click();
  await expect(editor(page).getByText("First line.", { exact: true })).toBeVisible();
  await toolbarButton(page, "Redo").click();
  await expect(editor(page).getByText("First line. Second part.")).toBeVisible();

  // The keys do the same, and what the person ends in is what is saved.
  await page.keyboard.press("Control+z");
  await expect(editor(page).getByText("First line.", { exact: true })).toBeVisible();
  await page.keyboard.press("Control+Shift+z");
  await expect(editor(page).getByText("First line. Second part.")).toBeVisible();
  await expect.poll(saved).toContain("First line. Second part.");

  await page.reload();
  await expect(editor(page).getByText("First line. Second part.")).toBeVisible();
});

test("hyperlink: an address typed in the text becomes a link, kept after a reload; an unsafe one stays text", async ({ page }) => {
  await createDocument(page, { text: "# Links\n\nLook here:" });

  await caretAtEndOf(page, "Look here:");
  await page.keyboard.type(" https://example.com/help and javascript:alert(1) ");
  await expect(editor(page).locator('a[href="https://example.com/help"]')).toHaveCount(1);
  await expect(editor(page).locator('a[href^="javascript"]')).toHaveCount(0);
  await waitUntilSaved(page);

  await page.reload();
  await expect(editor(page).locator('a[href="https://example.com/help"]')).toHaveText("https://example.com/help");
  await expect(editor(page).locator('a[href^="javascript"]')).toHaveCount(0);
  await expect(editor(page).getByText("javascript:alert(1)")).toBeVisible();
});

test("image: a pasted picture is stored with the document, still there after a reload, and in the Word file", async ({ page }) => {
  await createDocument(page, { text: "# Gallery\n\nA picture follows." });

  await caretAtEndOf(page, "A picture follows.");
  await page.keyboard.press("Enter");
  const saved = page.waitForResponse(isContentSave);
  await pasteHtml(page, `<p><img src="${PNG_DATA_URL}" alt="Company logo"></p>`);
  await saved;
  await waitUntilSaved(page);
  await expect(editor(page).locator('img[alt="Company logo"]')).toHaveCount(1);

  await page.reload();
  const picture = editor(page).locator('img[alt="Company logo"]');
  await expect(picture).toHaveCount(1);
  // Moved into the server's asset storage on save, not kept inline.
  await expect(picture).toHaveAttribute("src", /\/api\/v1\/assets\//);
  await expect.poll(() => picture.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);

  const file = await downloadExport(page, "DOCX");
  expect(zipNames(file.bytes).filter((name) => name.startsWith("word/media/"))).toHaveLength(1);
});

test("caption: a Word file's caption is edited in the browser and is still a caption in the Word file", async ({ page }) => {
  await createDocument(page, { file: path.join(GOLDEN, "08-caption.docx") });

  const captions = editor(page).locator('p[data-caption="true"]');
  await expect(captions).toHaveText(["Figure 1: The blue box.", "Table 1. Quarterly prices"]);
  await captions.first().click();
  await expect(editor(page)).toBeFocused();
  await page.keyboard.press("End");  await page.keyboard.type(" Edited.");
  await waitUntilSaved(page);
  await page.reload();
  await expect(captions).toHaveText(["Figure 1: The blue box. Edited.", "Table 1. Quarterly prices"]);

  const body = unzipped((await downloadExport(page, "DOCX")).bytes, "word/document.xml");
  expect(body).toContain("Figure 1: The blue box. Edited.");
  // The edited caption is written anew, in the Caption style.
  expect(body).toMatch(/<w:pStyle w:val="Caption"\/>.*?Figure 1: The blue box\. Edited\./);
});

test("PDF import: a PDF's text becomes a document that can be edited and exported", async ({ page }) => {
  const pdf = makePdf(["Annual summary", "Sales rose in the north.", "Costs fell in the south."]);
  await createDocument(page, { file: { name: "summary.pdf", mimeType: "application/pdf", buffer: pdf } });

  await expect(editor(page).getByText("Sales rose in the north.")).toBeVisible();
  await expect(editor(page).getByText("Costs fell in the south.")).toBeVisible();

  await caretAtEndOf(page, "Costs fell in the south.");
  await page.keyboard.type(" Edited.");
  await waitUntilSaved(page);
  await page.reload();
  await expect(editor(page).getByText("Costs fell in the south. Edited.")).toBeVisible();

  const body = unzipped((await downloadExport(page, "DOCX")).bytes, "word/document.xml");
  expect(body).toContain("Sales rose in the north.");
  expect(body).toContain("Edited.");
});

test("delete: a deleted document is gone for good, its address no longer opens", async ({ page }) => {
  const id = await createDocument(page, { text: "# Short lived\n\nNot for long." });

  await page.goto("/documents");
  await page.getByRole("button", { name: "Delete Short lived" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete for good" }).click();
  await expect(page.getByRole("link", { name: "Short lived" })).toHaveCount(0);

  const response = await page.goto(`/documents/${id}`);
  expect(response?.status()).toBe(404);
  await page.goto("/documents");
  await expect(page.getByRole("link", { name: "Short lived" })).toHaveCount(0);
});
