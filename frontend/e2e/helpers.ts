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

/** Through the document flow (S2-020: content -> structure -> look), ending in the editor; returns the
 * document's id. `template`: applied in the look step; without one the editor opens unformatted. */
export async function createDocument(
  page: Page,
  source: { text: string } | { file: string },
  { template, autolink, layout, onReview }: { template?: string; autolink?: boolean; layout?: boolean; onReview?: () => Promise<void> } = {},
): Promise<string> {
  await page.goto("/new");
  if ("text" in source) {
    await page.getByLabel("Your text").fill(source.text);
  } else {
    await page.getByRole("button", { name: "Upload a file" }).click();
    await page.locator('input[type="file"][accept=".txt,.docx,.pdf"]').setInputFiles(source.file);
    if (autolink) await page.getByLabel("Turn web and e-mail addresses written as plain text into links").check();
    if (layout) await page.getByRole("radio", { name: /Close to the original layout/ }).check();
  }
  await page.getByRole("button", { name: "Analyse the structure" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Check the structure" })).toBeVisible();
  if (onReview) await onReview();
  await page.getByRole("button", { name: "Confirm the structure" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Choose the look" })).toBeVisible();
  if (template) {
    await page.getByRole("button", { name: new RegExp(template) }).first().click();
    await page.getByRole("button", { name: "Apply and open the editor" }).click();
  } else {
    await page.getByRole("button", { name: "Open without formatting" }).click();
  }
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

/** Opens one of the classic editor's side panels by its name in the interface language, e.g. "Templates". */
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
