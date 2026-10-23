import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { API, createDocument, editor, signUp } from "./helpers";

/**
 * B-035A: a Word file over the hosting's 4.5 MB request limit (a 4.9 MB one was refused with 413 on the Preview,
 * 2026-10-23) goes up in parts and is imported whole -- the document keeps the very file sent (its SHA-256) --
 * and no request the browser makes is over the limit. A file over the 10 MB cap is refused with a clear message.
 */

const backend = path.resolve(__dirname, "..", "..", "backend");
const python = process.platform === "win32" ? path.join(backend, "venv", "Scripts", "python.exe") : path.join(backend, "venv", "bin", "python");
const LIMIT = 4.5 * 1024 * 1024;

/** A Word file with one picture that doesn't compress, about `megabytes` large, the same every run. */
function largeDocx(megabytes: number): string {
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
    "document.add_paragraph('Quarterly report: revenue 1,250 EUR on 2026-10-23.')",
    "document.add_picture(image, width=Cm(12))",
    "document.add_paragraph('Text after the picture.')",
    "document.save(sys.argv[1])",
  ].join("\n");
  execFileSync(python, ["-c", script, out, String(megabytes)]);
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
