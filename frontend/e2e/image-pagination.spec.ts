import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { API, createDocument, editor, signUp } from "./helpers";

/**
 * Tall pictures and the editor's pages (B-037). A picture is one unit on the page: one that fits on an empty page but not
 * in what is left of this one moves whole to the next page, and one taller than a page's text area is drawn smaller, in
 * its own proportions, to fit it (95% of it, as the PDF export draws it) -- never across a page edge. Only how it is drawn
 * changes: the stored picture, the document and its exports keep the picture's own bytes. Synthetic pictures only: a
 * coloured grid made here, the size of a phone screenshot (946 x 2048).
 */

const backend = path.resolve(__dirname, "..", "..", "backend");
const python = process.platform === "win32" ? path.join(backend, "venv", "Scripts", "python.exe") : path.join(backend, "venv", "bin", "python");
const TEXT = "Report title\n\nFirst paragraph of the report.\n\nSecond paragraph of the report.";

/** A PNG of a coloured grid, `width` x `height` px, the same every run. */
function gridPng(width: number, height: number): string {
  const out = path.join(mkdtempSync(path.join(os.tmpdir(), "smartdoc-b037-")), `grid-${width}x${height}.png`);
  const script = [
    "import sys",
    "from PIL import Image, ImageDraw",
    "w, h = int(sys.argv[2]), int(sys.argv[3])",
    "image = Image.new('RGB', (w, h), (240, 240, 240))",
    "draw = ImageDraw.Draw(image)",
    "for i, y in enumerate(range(0, h, 128)):",
    "    draw.rectangle([0, y, w - 1, y + 63], fill=((i * 53) % 256, (i * 97) % 256, 200))",
    "draw.rectangle([0, 0, w - 1, h - 1], outline=(0, 0, 0), width=6)",
    "image.save(sys.argv[1])",
  ].join("\n");
  execFileSync(python, ["-c", script, out, String(width), String(height)]);
  return out;
}

/** PDF: each picture's drawn box (pypdf's content-stream walk) inside the page's text area and in proportion; DOCX:
 * each picture's extent inside the text area (width and 95% of the height), in proportion, its media the very file. */
const CHECK_EXPORTS = String.raw`
import hashlib, io, json, re, sys, zipfile
from pypdf import PdfReader
from PIL import Image
pdf_path, docx_path, original = sys.argv[1], sys.argv[2], sys.argv[3]
problems, pdf_images = [], 0
source = Image.open(original)
own = source.width / source.height
reader = PdfReader(pdf_path)
for number, page in enumerate(reader.pages, 1):
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    boxes = []
    def visit(op, args, cm, tm):
        if op == b"Do":
            boxes.append((cm[0], cm[3], cm[4], cm[5]))
    page.extract_text(visitor_operand_before=visit)
    for w, h, x, y in boxes:
        pdf_images += 1
        if x < -1 or y < -1 or x + w > width + 1 or y + h > height + 1:
            problems.append(f"PDF page {number}: picture outside the page")
        if h > height * 0.95:
            problems.append(f"PDF page {number}: picture taller than the text area ({h:.0f} of {height:.0f} pt)")
        if abs(w / h - own) / own > 0.01:
            problems.append(f"PDF page {number}: picture out of proportion")
with zipfile.ZipFile(docx_path) as package:
    assert package.testzip() is None
    xml = package.read("word/document.xml").decode()
    media = [package.read(name) for name in package.namelist() if name.startswith("word/media/")]
    sect = re.findall(r'<w:pgSz w:w="(\d+)" w:h="(\d+)"[^>]*/>.*?<w:pgMar w:top="(-?\d+)" w:right="(\d+)" w:bottom="(-?\d+)" w:left="(\d+)"', xml, re.S)[-1]
    page_w, page_h, top, right, bottom, left = (int(v) * 635 for v in sect)  # twips -> EMU
    text_w, text_h = page_w - left - right, page_h - abs(top) - abs(bottom)
    extents = [(int(cx), int(cy)) for cx, cy in re.findall(r'<wp:extent cx="(\d+)" cy="(\d+)"/>', xml)]
    for cx, cy in extents:
        if cx > text_w + 635 or cy > text_h * 0.95 + 635:
            problems.append(f"DOCX picture {cx}x{cy} EMU larger than the text area {text_w}x{text_h}")
        if abs(cx / cy - own) / own > 0.01:
            problems.append("DOCX picture out of proportion")
    original_png = open(original, "rb").read()
    if not any(Image.open(io.BytesIO(data)).tobytes() == source.tobytes() for data in media):
        problems.append("DOCX media is not the picture")
print(json.dumps({"problems": problems, "pdfImages": pdf_images, "docxImages": len(extents)}))
`;

type Box = { top: number; bottom: number; width: number; height: number; naturalWidth: number; naturalHeight: number; complete: boolean };
type Layout = { pages: { top: number; height: number }[]; marginTop: number; marginBottom: number; images: Box[] };

/** The pages and every picture, in the page layout's own px (zoom taken out, as pagination.ts measures). */
async function layout(page: Page): Promise<Layout> {
  return editor(page).evaluate((root) => {
    const container = root.closest<HTMLElement>("[data-page-height]")!;
    const scale = Number(container.dataset.scale) || 1;
    const origin = container.getBoundingClientRect().top;
    return {
      pages: Array.from(container.querySelectorAll<HTMLElement>("[data-page]")).map((sheet) => ({ top: parseFloat(sheet.style.top), height: parseFloat(sheet.style.height) })),
      marginTop: Number(container.dataset.marginTop),
      marginBottom: Number(container.dataset.marginBottom),
      images: Array.from(root.querySelectorAll("img")).map((img) => {
        const box = img.getBoundingClientRect();
        return {
          top: (box.top - origin) / scale,
          bottom: (box.bottom - origin) / scale,
          width: box.width / scale,
          height: box.height / scale,
          naturalWidth: img.naturalWidth,
          naturalHeight: img.naturalHeight,
          complete: img.complete && img.naturalWidth > 0,
        };
      }),
    };
  });
}

/** Each picture loaded, whole inside one page's text area (1 px of rounding allowed), in its own proportions. */
function problems(laid: Layout, count: number): string[] {
  const found: string[] = [];
  if (laid.images.length !== count) found.push(`${laid.images.length} pictures, expected ${count}`);
  laid.images.forEach((image, index) => {
    if (!image.complete) return found.push(`picture ${index} not loaded`);
    const sheet = laid.pages.find((one) => image.top >= one.top + laid.marginTop - 1 && image.top < one.top + one.height);
    if (!sheet) return found.push(`picture ${index} starts outside every page's text area (top ${image.top.toFixed(1)})`);
    const bottom = sheet.top + sheet.height - laid.marginBottom;
    if (image.bottom > bottom + 1) found.push(`picture ${index} crosses its page's bottom: ${image.bottom.toFixed(1)} > ${bottom.toFixed(1)}`);
    const drawn = image.width / image.height;
    const own = image.naturalWidth / image.naturalHeight;
    if (Math.abs(drawn - own) / own > 0.01) found.push(`picture ${index} out of proportion: ${drawn.toFixed(3)} vs ${own.toFixed(3)}`);
  });
  return found;
}

async function pick(page: Page, files: string[]) {
  await page.getByRole("button", { name: "Add element" }).click();
  const [chooser] = await Promise.all([page.waitForEvent("filechooser"), page.getByRole("button", { name: "Image" }).click()]);
  await chooser.setFiles(files);
}

async function waitUntilSaved(page: Page) {
  await expect(page.getByText("Saved", { exact: true }).first()).toBeVisible();
}

async function caretAtEndOf(page: Page, text: string) {
  await editor(page).getByText(text).click();
  await page.keyboard.press("End");
}

for (const v2 of [false, true]) {
  test(`${v2 ? "2.0" : "classic"} editor: a screenshot taller than a page is drawn whole inside one page, in its proportions`, async ({ page }) => {
    await signUp(page);
    const id = await createDocument(page, { text: TEXT });
    if (v2) await page.goto(`/documents/${id}?editor=2`);
    await caretAtEndOf(page, "Second paragraph of the report.");
    await pick(page, [gridPng(946, 2048)]);
    await expect.poll(async () => problems(await layout(page), 1)).toEqual([]);
    const laid = await layout(page);
    const fit = 0.95 * (laid.pages[0].height - laid.marginTop - laid.marginBottom);
    expect(laid.images[0].height).toBeGreaterThan(fit - 2); // drawn as large as the page allows, not smaller
    await waitUntilSaved(page);
    await page.reload();
    await expect.poll(async () => problems(await layout(page), 1)).toEqual([]);
  });
}

test("several tall screenshots in a row: each whole on a page of its own, in order; the text after them follows", async ({ page }) => {
  await signUp(page);
  const id = await createDocument(page, { text: TEXT });
  await caretAtEndOf(page, "First paragraph of the report.");
  const files = [gridPng(946, 2048), gridPng(946, 2100), gridPng(946, 1900)];
  await pick(page, files);
  await expect.poll(async () => problems(await layout(page), 3)).toEqual([]);
  const laid = await layout(page);
  const pageOf = (y: number) => laid.pages.findIndex((one) => y >= one.top && y < one.top + one.height);
  const pagesUsed = laid.images.map((image) => pageOf(image.top));
  expect(new Set(pagesUsed).size).toBe(3); // one page each
  expect([...pagesUsed].sort((a, b) => a - b)).toEqual(pagesUsed); // in order
  const after = await editor(page).getByText("Second paragraph of the report.").evaluate((element) => element.getBoundingClientRect().top);
  const lastImage = await editor(page).locator("img").last().evaluate((element) => element.getBoundingClientRect().bottom);
  expect(after).toBeGreaterThan(lastImage); // the paragraph after the pictures comes after them
  await waitUntilSaved(page);
  const stored = await (await page.request.get(`${API}/documents/${id}`)).json();
  // The saved document: the three pictures between the two paragraphs, nothing else added.
  expect(stored.elements.map((one: { type: string }) => one.type).slice(-5)).toEqual(["paragraph", "image", "image", "image", "paragraph"]);
  expect(stored.elements.filter((one: { type: string }) => one.type === "image")).toHaveLength(3);
});

test("a picture that fits on an empty page but not below the text moves whole to the next page; a small one keeps its size", async ({ page }) => {
  await signUp(page);
  const lines = Array.from({ length: 14 }, (_, i) => `Paragraph ${i + 1} with enough words to take a full line of the page or a little more.`).join("\n\n");
  await createDocument(page, { text: lines });
  await caretAtEndOf(page, "Paragraph 14 with enough words");
  await pick(page, [gridPng(600, 900)]);
  await expect.poll(async () => problems(await layout(page), 1)).toEqual([]);
  const laid = await layout(page);
  expect(laid.images[0].top).toBeGreaterThanOrEqual(laid.pages[1].top + laid.marginTop - 1); // on page 2, at its top
  await caretAtEndOf(page, "Paragraph 1 with enough words");
  await pick(page, [gridPng(300, 200)]);
  await expect.poll(async () => problems(await layout(page), 2)).toEqual([]);
  // A picture shorter than a page is drawn as before: across the text column (as the PDF export draws one with no size
  // of its own), in its proportions -- the page fit doesn't make it smaller.
  const small = (await layout(page)).images.find((image) => image.naturalWidth === 300)!;
  const column = await editor(page)
    .getByText("Paragraph 1 with enough words")
    .evaluate((element) => element.getBoundingClientRect().width / (Number(element.closest<HTMLElement>("[data-page-height]")!.dataset.scale) || 1));
  expect(Math.abs(small.width - column)).toBeLessThan(2);
  expect(Math.abs(small.height - small.width / 1.5)).toBeLessThan(2);
});

test("undo and redo of a tall picture keep the pages right; the exports keep its bytes and fit it to the page", async ({ page }) => {
  await signUp(page);
  const id = await createDocument(page, { text: TEXT });
  await caretAtEndOf(page, "Second paragraph of the report.");
  const file = gridPng(946, 2048);
  // The save that carries the picture, answered: undoing while it is still on its way is another case (B-038).
  const pictureSaved = page.waitForResponse((response) => /\/content$/.test(response.url()) && (response.request().postData() ?? "").includes("data:image/"));
  await pick(page, [file]);
  expect((await pictureSaved).ok()).toBe(true);
  await expect.poll(async () => problems(await layout(page), 1)).toEqual([]);
  await waitUntilSaved(page);
  await editor(page).getByText("First paragraph of the report.").click();
  // Each step saved before the next (an undo and redo inside one autosave pause leaves the status behind: B-038).
  const isSave = (response: { url: () => string; request: () => { method: () => string } }) => /\/content$/.test(response.url()) && ["PATCH", "PUT"].includes(response.request().method());
  const undoSaved = page.waitForResponse(isSave);
  await page.keyboard.press("Control+z");
  await expect.poll(async () => (await layout(page)).images.length).toBe(0);
  expect((await undoSaved).ok()).toBe(true);
  const redoSaved = page.waitForResponse(isSave);
  await page.keyboard.press("Control+y");
  await expect.poll(async () => problems(await layout(page), 1)).toEqual([]);
  expect((await redoSaved).ok()).toBe(true);
  await waitUntilSaved(page);

  // The stored picture is the very file (its bytes), whatever size it is drawn at.
  const stored = await (await page.request.get(`${API}/documents/${id}`)).json();
  const image = stored.elements.find((one: { type: string }) => one.type === "image");
  const asset = Buffer.from(await (await page.request.get(`${API}/assets/${image.image.assetId}`)).body());
  expect(asset.equals(readFileSync(file))).toBe(true);

  // PDF and DOCX: checked by their own parsers (python) -- every picture inside the page's text area, in proportion.
  const pdf = path.join(mkdtempSync(path.join(os.tmpdir(), "smartdoc-b037-")), "out.pdf");
  const docx = pdf.replace("out.pdf", "out.docx");
  writeFileSync(pdf, Buffer.from(await (await page.request.get(`${API}/documents/${id}/export/pdf`)).body()));
  writeFileSync(docx, Buffer.from(await (await page.request.get(`${API}/documents/${id}/export/docx`)).body()));
  const report = JSON.parse(execFileSync(python, ["-c", CHECK_EXPORTS, pdf, docx, file]).toString());
  expect(report.problems).toEqual([]);
  expect(report.pdfImages).toBe(1);
  expect(report.docxImages).toBe(1);
});

test("at another zoom the tall picture still sits whole inside one page", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { text: TEXT });
  await caretAtEndOf(page, "Second paragraph of the report.");
  await pick(page, [gridPng(946, 2048)]);
  await expect.poll(async () => problems(await layout(page), 1)).toEqual([]);
  for (const button of ["Zoom in", "Zoom in", "Zoom out", "Zoom out", "Zoom out"]) {
    const before = await editor(page).evaluate((root) => root.closest<HTMLElement>("[data-page-height]")!.dataset.scale);
    await page.getByRole("button", { name: button, exact: true }).first().click();
    await expect.poll(() => editor(page).evaluate((root) => root.closest<HTMLElement>("[data-page-height]")!.dataset.scale)).not.toBe(before);
    await expect.poll(async () => problems(await layout(page), 1)).toEqual([]);
  }
});
