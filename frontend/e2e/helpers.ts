import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { inflateRawSync } from "node:zlib";

import { expect, type Page, type Response } from "@playwright/test";

/** The golden Word documents the backend's tests use too (backend/tests/fixtures/documents). */
export const GOLDEN = path.resolve(__dirname, "..", "..", "backend", "tests", "fixtures", "documents");

export const PASSWORD = "a long enough password";

/** The E2E backend (playwright.config.ts), for requests made with the browser's own session. */
export const API = "http://localhost:8100/api/v1";

let counter = 0;

/** An address no other test has signed up with. */
export function uniqueEmail(name = "user"): string {
  counter += 1;
  return `${name}-${Date.now()}-${counter}@example.com`;
}

export async function signUp(page: Page, email = uniqueEmail()): Promise<string> {
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: /Welcome back/ })).toBeVisible();
  return email;
}

/** The editor's text area (the template previews use ProseMirror too). */
export function editor(page: Page) {
  return page.locator(".paged-editor .ProseMirror");
}

/** Puts the caret at the end of the block holding `text`, with the editor surely focused (a click in the
 * first moments after loading can leave the caret at the start). */
export async function caretAtEndOf(page: Page, text: string | RegExp, options: { exact?: boolean } = {}) {
  await editor(page).getByText(text, options).first().click();
  await expect(editor(page)).toBeFocused();
  await page.keyboard.press("End");
}

/** A button of the editor's rich-text toolbar (the Properties panel repeats some of them further down the page). */
export function toolbarButton(page: Page, name: string) {
  return page.getByRole("button", { name, exact: true }).first();
}

/** Clicks a toggle of the rich-text toolbar and waits until it shows `pressed` and the editor has the focus back,
 * so the keys typed next reach the editor (the click moves the focus away and the toolbar gives it back). */
export async function toggleToolbar(page: Page, name: string, pressed: boolean) {
  await toolbarButton(page, name).click();
  await expect(toolbarButton(page, name)).toHaveAttribute("aria-pressed", String(pressed));
  await expect(editor(page)).toBeFocused();
}

/** Through the new-document wizard, ending in the editor; returns the document's id. */
export async function createDocument(
  page: Page,
  source: { text: string } | { file: string | { name: string; mimeType: string; buffer: Buffer } },
  { template, autolink, onReview }: { template?: string; autolink?: boolean; onReview?: () => Promise<void> } = {},
): Promise<string> {
  await page.goto("/new");
  if (template) {
    await page.getByRole("button", { name: new RegExp(template) }).first().click();
  } else {
    await page.getByRole("button", { name: /Something else/ }).click();
  }
  await page.getByRole("button", { name: "Continue" }).click();

  if ("text" in source) {
    await page.getByPlaceholder("Paste your raw text here...").fill(source.text);
  } else {
    await page.getByRole("button", { name: "Upload a file" }).click();
    await page.locator('input[type="file"][accept=".txt,.docx,.pdf"]').setInputFiles(source.file);
    if (autolink) await page.getByLabel("Turn web and e-mail addresses written as plain text into links").check();
  }
  await page.getByRole("button", { name: "Continue" }).click();

  await page.getByRole("button", { name: template ? "Apply the template now" : "Decide later" }).click();
  await page.getByRole("button", { name: "Create document" }).click();
  await expect(page.getByRole("heading", { name: "Here’s what we found" })).toBeVisible();
  if (onReview) await onReview();
  await page.getByRole("button", { name: "Looks good, continue" }).click();
  await page.waitForURL(/\/documents\/[0-9a-f-]{36}$/);
  await expect(editor(page)).toBeVisible();
  return page.url().split("/").pop()!;
}

/** A save of what is typed: PATCH /content with what changed, or PUT /content with the whole document (PERF-003). */
export function isContentSave(response: Response): boolean {
  return response.url().endsWith("/content") && ["PATCH", "PUT"].includes(response.request().method()) && response.ok();
}

/** The newest e-mail the E2E backend sent to `to` holding `containing` (an .eml file in its outbox,
 * playwright.config.ts), as text. */
export async function lastEmail(to: string, containing = ""): Promise<string> {
  const outbox = process.env.E2E_OUTBOX_DIR!;
  let found: string | undefined;
  await expect
    .poll(() => {
      const names = readdirSync(outbox).filter((name) => name.endsWith(".eml")).sort();
      found = names
        .map((name) => readFileSync(path.join(outbox, name), "utf-8"))
        .filter((message) => message.includes(`To: ${to}`) && message.includes(containing))
        .at(-1);
      return found !== undefined;
    })
    .toBe(true);
  return found!;
}

/** Waits until everything typed is saved (the status bar says so). */
export async function waitUntilSaved(page: Page) {
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
}

/** Opens one of the editor's side panels by its (Bulgarian) name, e.g. "Шаблони". */
export async function openPanel(page: Page, name: string) {
  const tab = page.getByRole("button", { name, exact: true });
  if ((await tab.getAttribute("aria-pressed")) !== "true") await tab.click();
}

/** One file out of a ZIP (a .docx is one), read with Node's own zlib. */
export function unzipped(zip: Buffer, name: string): string {
  const end = zip.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  const count = zip.readUInt16LE(end + 10);
  let offset = zip.readUInt32LE(end + 16);
  for (let index = 0; index < count; index += 1) {
    const method = zip.readUInt16LE(offset + 10);
    const size = zip.readUInt32LE(offset + 20);
    const nameLength = zip.readUInt16LE(offset + 28);
    const entry = zip.toString("utf8", offset + 46, offset + 46 + nameLength);
    if (entry === name) {
      const local = zip.readUInt32LE(offset + 42);
      const start = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28);
      const data = zip.subarray(start, start + size);
      return (method === 0 ? data : inflateRawSync(data)).toString("utf8");
    }
    offset += 46 + nameLength + zip.readUInt16LE(offset + 30) + zip.readUInt16LE(offset + 32);
  }
  throw new Error(`${name} isn't in the file`);
}

/** The names of every file in a ZIP (a .docx is one). */
export function zipNames(zip: Buffer): string[] {
  const end = zip.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  const count = zip.readUInt16LE(end + 10);
  let offset = zip.readUInt32LE(end + 16);
  const names: string[] = [];
  for (let index = 0; index < count; index += 1) {
    const nameLength = zip.readUInt16LE(offset + 28);
    names.push(zip.toString("utf8", offset + 46, offset + 46 + nameLength));
    offset += 46 + nameLength + zip.readUInt16LE(offset + 30) + zip.readUInt16LE(offset + 32);
  }
  return names;
}

/** Pastes HTML into the editor as a browser's paste would (the clipboard itself isn't reachable from a test). */
export async function pasteHtml(page: Page, html: string) {
  await editor(page).evaluate((element, markup) => {
    const data = new DataTransfer();
    data.setData("text/html", markup);
    data.setData("text/plain", "pasted");
    element.dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true }));
  }, html);
}

/** A one-pixel picture, as the data address a paste carries. */
export const PNG_DATA_URL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

/** Through the export menu: downloads the document as `format`; returns the file's name and bytes. */
export async function downloadExport(page: Page, format: "DOCX" | "PDF"): Promise<{ name: string; bytes: Buffer }> {
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await page.getByRole("button", { name: format, exact: true }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: `Download ${format}` }).click();
  const file = await download;
  const bytes = readFileSync((await file.path())!);
  // The export's check: the file, read back, holds every word of the document.
  await expect(page.getByRole("status").filter({ hasText: "Every word of the document is in the file." })).toBeVisible();
  await page.getByRole("button", { name: "Export", exact: true }).click({ force: true }); // closes the menu
  return { name: file.suggestedFilename(), bytes };
}

/** A one-page, text-only PDF built here (Helvetica, one line per entry), so no binary is committed. */
export function makePdf(lines: string[]): Buffer {
  const escape = (text: string) => text.replace(/[\\()]/g, (char) => `\\${char}`);
  const stream = `BT /F1 12 Tf 72 720 Td 18 TL ${lines.map((line) => `(${escape(line)}) Tj T*`).join(" ")} ET`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((body, index) => {
    offsets.push(pdf.length);
    pdf += `${index + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const offset of offsets) pdf += `${String(offset).padStart(10, "0")} 00000 n \n`;
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(pdf, "latin1");
}
