import path from "node:path";

import { expect, type Page } from "@playwright/test";

/** The golden Word documents the backend's tests use too (backend/tests/fixtures/documents). */
export const GOLDEN = path.resolve(__dirname, "..", "..", "backend", "tests", "fixtures", "documents");

export const PASSWORD = "a long enough password";

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

/** Through the new-document wizard, ending in the editor; returns the document's id. */
export async function createDocument(
  page: Page,
  source: { text: string } | { file: string },
  { template }: { template?: string } = {},
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
  }
  await page.getByRole("button", { name: "Continue" }).click();

  await page.getByRole("button", { name: template ? "Apply the template now" : "Decide later" }).click();
  await page.getByRole("button", { name: "Create document" }).click();
  await expect(page.getByRole("heading", { name: "Here’s what we found" })).toBeVisible();
  await page.getByRole("button", { name: "Looks good, continue" }).click();
  await page.waitForURL(/\/documents\/[0-9a-f-]{36}$/);
  await expect(editor(page)).toBeVisible();
  return page.url().split("/").pop()!;
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
