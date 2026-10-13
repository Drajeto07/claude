import { expect, test } from "@playwright/test";

import { API, signUp } from "./helpers";

/**
 * SmartDoc 2.0 screens in a real browser (production build, throwaway API): the interface
 * language (D-010) -- chosen from the browser's language, switched by hand, remembered across
 * visits -- the dashboard (S2-014) and New Project (S2-015).
 */

test.describe("in a browser that prefers Bulgarian", () => {
  test.use({ locale: "bg-BG" });

  test("the sign-in page starts in Bulgarian, and a switch to English is remembered", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { level: 1, name: "Вход" })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "bg");
    await expect(page.getByLabel("Имейл")).toBeVisible();

    await page.getByRole("button", { name: "English" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");

    await page.reload();  // a new visit: the choice holds, though the browser still prefers Bulgarian
    await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    await page.goto("/register");
    await expect(page.getByRole("heading", { level: 1, name: "Create your account" })).toBeVisible();
  });
});

test("an English browser starts in English; Settings switch the whole interface to Bulgarian and it stays", async ({ page }) => {
  await signUp(page);  // English labels: the browser's default is en-US
  await expect(page.locator("html")).toHaveAttribute("lang", "en");

  await page.goto("/settings/account");
  await page.getByRole("radio", { name: "Български" }).check();
  await expect(page.getByRole("navigation", { name: "Основна навигация" }).getByRole("link", { name: "Проекти" })).toBeVisible();

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: /Добре дошли отново/ })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: /Добре дошли отново/ })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "bg");
});

test("from an empty dashboard to New Project: a description suggests a type, Document opens the document flow", async ({ page }) => {
  await signUp(page);
  const gallery = page.getByRole("region", { name: "Recent projects" });
  await expect(gallery.getByText("No projects yet.")).toBeVisible();

  await page.getByLabel("What do you want to create?").fill("a poster for a concert");
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page).toHaveURL(/\/projects\/new\?describe=a(%20|\+)poster/);
  await expect(page.getByRole("status")).toContainText("Suggested from your description: Poster");
  await expect(page.getByText("Coming soon").first()).toBeVisible();

  await page.getByRole("region", { name: "Start now" }).getByRole("link", { name: /^Document/ }).click();
  await expect(page).toHaveURL(/\/new$/);
});

test("the dashboard search finds a project by its title", async ({ page }) => {
  await signUp(page);
  // Two projects through the API with this browser's session (from the app's own origin).
  for (const title of ["Quarterly budget", "Garden notes"]) {
    const created = await page.request.post(`${API}/documents`, {
      data: { text: `${title}\n\nSome text for ${title}.`, title },
      headers: { Origin: "http://localhost:3100" },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
  }
  await page.goto("/");
  const gallery = page.getByRole("region", { name: "Recent projects" });
  await expect(gallery.getByRole("link", { name: /Quarterly budget/ })).toBeVisible();
  await expect(gallery.getByRole("link", { name: /Garden notes/ })).toBeVisible();

  await page.getByLabel("Search your projects").fill("budget");
  await expect(gallery.getByRole("link", { name: /Garden notes/ })).toHaveCount(0);
  await expect(gallery.getByRole("link", { name: /Quarterly budget/ })).toBeVisible();
});

test("signed out, New Project sends you to sign in and back", async ({ page }) => {
  await page.goto("/projects/new?describe=cv");
  await expect(page).toHaveURL(/\/login\?next=%2Fprojects%2Fnew%3Fdescribe%3Dcv/);
});
