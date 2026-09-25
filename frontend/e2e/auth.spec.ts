import { expect, test } from "@playwright/test";

import { PASSWORD, createDocument, signUp, uniqueEmail } from "./helpers";

test("sign up, sign out and sign in again", async ({ page }) => {
  const email = await signUp(page);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /Welcome back/ })).toBeVisible();
});

test("a wrong password is refused without saying which part was wrong", async ({ page }) => {
  const email = await signUp(page);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("not the password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByText("Invalid email or password.")).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
});

test("a signed-out visitor is sent to sign in, and back afterwards", async ({ page }) => {
  const email = await signUp(page);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.goto("/documents");
  await expect(page).toHaveURL(/\/login\?next=%2Fdocuments$/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/documents$/);
});

test("someone else's document can't be opened, even with its address", async ({ page, browser }) => {
  await signUp(page, uniqueEmail("owner"));
  const documentId = await createDocument(page, { text: "# Private plans\n\nOnly for the owner." });

  const other = await browser.newContext();
  const stranger = await other.newPage();
  await signUp(stranger, uniqueEmail("stranger"));
  const response = await stranger.goto(`/documents/${documentId}`);

  expect(response?.status()).toBe(404);
  await expect(stranger.getByText("Private plans")).toHaveCount(0);
  await other.close();
});
