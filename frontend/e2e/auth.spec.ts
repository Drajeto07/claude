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

  const link = /http:\/\/localhost:3100\/reset-password#token=[A-Za-z0-9_-]+/.exec(await lastEmail(email, "/reset-password#token="))?.[0];
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

test("the address is confirmed with the link sent at sign-up, and the notice goes", async ({ page }) => {
  const email = await signUp(page);
  await expect(page.getByRole("region", { name: "Confirm your e-mail address" })).toContainText(email);

  const link = /http:\/\/localhost:3100\/verify-email#token=[A-Za-z0-9_-]+/.exec(await lastEmail(email, "/verify-email#token="))?.[0];
  expect(link).toBeTruthy();
  await page.goto(link!);
  await page.getByRole("button", { name: "Confirm my address" }).click();
  await expect(page.getByRole("heading", { name: "Address confirmed" })).toBeVisible();
  await expect(page).toHaveURL(/\/verify-email$/);

  await page.getByRole("link", { name: "Go to SmartDoc" }).click();
  await expect(page.getByRole("heading", { name: /Welcome back/ })).toBeVisible();
  await expect(page.getByRole("region", { name: "Confirm your e-mail address" })).toHaveCount(0);
});

test("a password changed in the account settings is the one to sign in with", async ({ page }) => {
  const email = await signUp(page);
  await page.getByRole("link", { name: "Your account" }).click();
  await expect(page.getByRole("heading", { name: "Your account" })).toBeVisible();

  const newPassword = "my changed long password";
  await page.getByLabel("Current password").fill(PASSWORD);
  await page.getByLabel("New password").fill(newPassword);
  await page.getByLabel("The new one again").fill(newPassword);
  await page.getByRole("button", { name: "Change the password" }).click();
  await expect(page.getByText("Your password is changed.")).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(newPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /Welcome back/ })).toBeVisible();
});

test("another browser signed in is listed, e-mailed about and signed out from the account page", async ({ page, browser }) => {
  const email = await signUp(page);
  const other = await browser.newContext();
  const elsewhere = await other.newPage();
  await elsewhere.goto("/login");
  await elsewhere.getByLabel("Email").fill(email);
  await elsewhere.getByLabel("Password").fill(PASSWORD);
  await elsewhere.getByRole("button", { name: "Sign in" }).click();
  await expect(elsewhere.getByRole("heading", { name: /Welcome back/ })).toBeVisible();
  expect(await lastEmail(email, "A new sign-in to your SmartDoc account")).not.toContain("127.0.0.1");

  await page.goto("/settings/account");
  const sessions = page.getByRole("region", { name: "Where you're signed in" });
  await expect(sessions.getByRole("listitem")).toHaveCount(2);
  await expect(sessions.getByText("This browser")).toHaveCount(1);
  await sessions.getByRole("button", { name: "Sign out every other browser" }).click();
  await expect(sessions.getByRole("listitem")).toHaveCount(1);

  await elsewhere.goto("/documents");
  await expect(elsewhere).toHaveURL(/\/login\?next=%2Fdocuments$/);
  await other.close();
});

test("an account deleted from the settings is gone: its documents and its sign-in", async ({ page }) => {
  const email = await signUp(page);
  await createDocument(page, { text: "# Mine alone\n\nA paragraph to be deleted." });
  await page.goto("/settings/account");

  const form = page.getByRole("form", { name: "Delete your account" });
  await form.getByLabel("Your password").fill(PASSWORD);
  await expect(form.getByRole("button", { name: "Delete my account" })).toBeDisabled();
  await form.getByLabel(/to confirm/).fill("delete my account");
  await form.getByRole("button", { name: "Delete my account" }).click();

  await expect(page).toHaveURL(/\/login\?deleted=1$/);
  await expect(page.getByRole("status")).toContainText("Your account is deleted");
  await lastEmail(email, "Your SmartDoc account is deleted");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid email or password.")).toBeVisible();
});
