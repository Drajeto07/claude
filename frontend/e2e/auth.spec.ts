import { expect, test } from "@playwright/test";

import { PASSWORD, createDocument, lastEmail, signUp, uniqueEmail } from "./helpers";

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

test("a forgotten password: a link by e-mail sets a new one, once, and the old one stops working", async ({ page }) => {
  const email = await signUp(page);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.getByRole("link", { name: "Forgot your password?" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send the link" }).click();
  await expect(page.getByText(/If an account uses that address/)).toBeVisible();

  const link = /http:\/\/localhost:3100\/reset-password#token=[A-Za-z0-9_-]+/.exec(await lastEmail(email))?.[0];
  expect(link).toBeTruthy();
  const newPassword = "a different long password";
  await page.goto(link!);
  await page.getByLabel("New password").fill(newPassword);
  await page.getByLabel("The same again").fill(newPassword);
  await page.getByRole("button", { name: "Save the new password" }).click();
  await expect(page.getByRole("heading", { name: "Password changed" })).toBeVisible();
  await expect(page).toHaveURL(/\/reset-password$/); // the used token is gone from the address bar

  // The link works once.
  await page.goto("/login");
  await page.goto(link!);
  await page.getByLabel("New password").fill("yet another long password");
  await page.getByLabel("The same again").fill("yet another long password");
  await page.getByRole("button", { name: "Save the new password" }).click();
  await expect(page.getByText("This link has expired or has already been used. Ask for a new one.")).toBeVisible();

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid email or password.")).toBeVisible();
  await page.getByLabel("Password").fill(newPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /Welcome back/ })).toBeVisible();
});
