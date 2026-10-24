import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { API, createDocument, editor, signUp, unzipped } from "./helpers";

/**
 * B-035A: a Word file over the hosting's 4.5 MB request limit (a 4.9 MB one was refused with 413 on the Preview,
 * 2026-10-23) goes up in parts and is imported whole -- the document keeps the very file sent (its SHA-256) --
 * and no request the browser makes is over the limit. A file over the 10 MB cap is refused with a clear message.
 */

const backend = path.resolve(__dirname, "..", "..", "backend");
const python = process.platform === "win32" ? path.join(backend, "venv", "Scripts", "python.exe") : path.join(backend, "venv", "bin", "python");
const LIMIT = 4.5 * 1024 * 1024;

/** A Word file with one picture that doesn't compress, about `megabytes` large, the same every run. */
function largeDocx(megabytes: number, title = ""): string {
  const out = path.join(mkdtempSync(path.join(os.tmpdir(), "smartdoc-b035a-")), `report-${megabytes}mb.docx`);
  const script = [
    "import io, random, sys",
    "from PIL import Image",
    "from docx import Document",
    "from docx.shared import Cm",
    "size = int(float(sys.argv[2]) * 1024 * 1024)",
    "side = int((size / 3) ** 0.5)",
    "image = io.BytesIO()",
    "Image.frombytes('RGB', (side, side), random.Random(7).randbytes(side * side * 3)).save(image, 'PNG', compress_level=0)",
    "document = Document()",
    "document.core_properties.title = sys.argv[3]",
    "document.add_paragraph('Quarterly report: revenue 1,250 EUR on 2026-10-23.')",
    "document.add_picture(image, width=Cm(12))",
    "document.add_paragraph('Text after the picture.')",
    "document.save(sys.argv[1])",
  ].join("\n");
  execFileSync(python, ["-c", script, out, String(megabytes), title]);
  return out;
}

test("a 4.9 MB Word file goes up in parts, no request over 4.5 MB, and is imported byte for byte", async ({ page }) => {
  test.setTimeout(120_000);
  const file = largeDocx(4.9);
  const bytes = readFileSync(file);
  expect(bytes.length).toBeGreaterThan(LIMIT);
  const sent: { url: string; size: number }[] = [];
  page.on("request", (request) => {
    if (request.url().startsWith(API)) sent.push({ url: request.url(), size: request.postDataBuffer()?.length ?? 0 });
  });

  await signUp(page);
  const id = await createDocument(page, { file });
  await expect(editor(page)).toContainText("Quarterly report: revenue 1,250 EUR on 2026-10-23.");

  const parts = sent.filter((request) => /\/jobs\/import-file\/uploads\/[^/]+\/parts\/\d+\?sha256=[0-9a-f]{64}$/.test(request.url));
  expect(parts.length).toBe(Math.ceil(bytes.length / (3 * 1024 * 1024)));
  expect(sent.filter((request) => request.url.endsWith("/jobs/import-file"))).toHaveLength(0); // not sent whole
  expect(Math.max(...sent.map((request) => request.size))).toBeLessThan(LIMIT);

  const document = await (await page.request.get(`${API}/documents/${id}`)).json();
  expect(document.sourcePackage.sha256).toBe(createHash("sha256").update(bytes).digest("hex"));
  expect(document.sourcePackage.size).toBe(bytes.length);
  await expect(editor(page).locator("img")).toHaveCount(1);
});

/** SHA-256 of a Word file's pictures (its ZIP checked by Python's zipfile), and for a PDF its pages and whether one
 * holds a picture (pypdf) -- so a download that isn't a whole, valid file fails here. */
function inspect(file: string): { media: string[]; pages?: number; images?: boolean } {
  const script = [
    "import hashlib, json, sys, zipfile",
    "path = sys.argv[1]",
    "if path.endswith('.pdf'):",
    "    from pypdf import PdfReader",
    "    reader = PdfReader(path)",
    "    print(json.dumps({'media': [], 'pages': len(reader.pages), 'images': any(page.images for page in reader.pages)}))",
    "else:",
    "    with zipfile.ZipFile(path) as package:",
    "        assert package.testzip() is None",
    "        print(json.dumps({'media': sorted(hashlib.sha256(package.read(n)).hexdigest() for n in package.namelist() if n.startswith('word/media/'))}))",
  ].join("\n");
  return JSON.parse(execFileSync(python, ["-c", script, file]).toString());
}

test("B-035B: a large document's picture is shown, and its DOCX and PDF downloads come whole, streamed", async ({ page }) => {
  test.setTimeout(180_000);
  const title = "Отчет за 2026";
  const file = largeDocx(4.9, title);
  const original = inspect(file).media;
  expect(original).toHaveLength(1);
  const streamed: string[] = [];
  page.on("response", (response) => {
    if (/\/assets\/|\/jobs\/[^/]+\/file$/.test(response.url()) && response.headers()["content-length"] === undefined) streamed.push(response.url());
  });
  await signUp(page);
  await createDocument(page, { file });

  // The 4.9 MB picture is drawn: the browser got all of it.
  const picture = editor(page).locator("img");
  await expect(picture).toHaveCount(1);
  await expect.poll(() => picture.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
  const served = await page.request.get(await picture.getAttribute("src").then((src) => new URL(src!, page.url()).toString()));
  expect(createHash("sha256").update(await served.body()).digest("hex")).toBe(original[0]); // the very picture

  for (const [format, signature] of [
    ["DOCX", "PK"],
    ["PDF", "%PDF"],
  ] as const) {
    await page.getByRole("button", { name: "Export", exact: true }).click();
    await page.getByRole("button", { name: format, exact: true }).click();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: `Download ${format}` }).click();
    const file = await download;
    expect(file.suggestedFilename()).toBe(`${title}.${format.toLowerCase()}`); // the Cyrillic title survives
    const savedPath = path.join(mkdtempSync(path.join(os.tmpdir(), "smartdoc-b035b-")), file.suggestedFilename());
    await file.saveAs(savedPath);
    expect(await file.failure()).toBeNull();
    const saved = readFileSync(savedPath);
    expect(saved.length).toBeGreaterThan(LIMIT);
    expect(saved.subarray(0, signature.length).toString("latin1")).toBe(signature);
    if (format === "DOCX") {
      expect(unzipped(saved, "word/document.xml")).toContain("Text after the picture.");
      expect(inspect(savedPath).media).toEqual(original); // the picture inside the downloaded file, byte for byte
    } else {
      expect(saved.subarray(-1024).toString("latin1")).toContain("%%EOF");
      const pdf = inspect(savedPath);
      expect(pdf.pages).toBeGreaterThanOrEqual(1);
      expect(pdf.images).toBe(true);
    }
    await page.getByRole("button", { name: "Export", exact: true }).click({ force: true }); // closes the menu
  }
  // The picture and both exports left the API in parts, not as one body.
  expect(streamed.filter((url) => url.includes("/assets/")).length).toBeGreaterThan(0);
  expect(streamed.filter((url) => url.endsWith("/file")).length).toBe(2);
});

test("a file over the 10 MB cap is refused with a message, before any part is sent", async ({ page }) => {
  const file = path.join(mkdtempSync(path.join(os.tmpdir(), "smartdoc-b035a-")), "too-big.docx");
  writeFileSync(file, Buffer.alloc(10 * 1024 * 1024 + 1));
  const parts: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/parts/")) parts.push(request.url());
  });
  await signUp(page);
  await page.goto("/new");
  await page.getByRole("button", { name: "Upload a file" }).click();
  await page.locator('input[type="file"][accept=".txt,.docx,.pdf"]').setInputFiles(file);
  await page.getByRole("button", { name: "Analyse the structure" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "The file is larger than the 10 MB your plan takes." })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Add your content" })).toBeVisible();
  expect(parts).toEqual([]);
});
