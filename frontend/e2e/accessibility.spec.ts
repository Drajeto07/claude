import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { createDocument, GOLDEN, openPanel, signUp } from "./helpers";

/**
 * The app itself is accessible (tracker FEAT-011): axe-core finds no serious or critical WCAG
 * 2.x A/AA violations on the main pages and in the editor, panels included.
 */
const AXE = path.resolve(__dirname, "..", "node_modules", "axe-core", "axe.min.js");

type Violation = { id: string; impact: string | null; help: string; nodes: { target: string[] }[] };

async function seriousViolations(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: AXE });
  const violations: Violation[] = await page.evaluate(async () => {
    const axe = (window as unknown as { axe: { run: (context: Document, options: object) => Promise<{ violations: Violation[] }> } }).axe;
    const result = await axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] } });
    return result.violations;
  });
  return violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => `${violation.id} (${violation.impact}): ${violation.help} -- ${violation.nodes.slice(0, 4).map((node) => node.target.join(" ")).join(" | ")}`);
}

async function expectAccessible(page: Page, where: string) {
  await page.waitForLoadState("networkidle");
  expect.soft(await seriousViolations(page), where).toEqual([]);
}

test("signed-out pages have no serious accessibility violations", async ({ page }) => {
  for (const route of ["/login", "/register", "/forgot-password"]) {
    await page.goto(route);
    await expectAccessible(page, route);
  }
});

test("the main pages and the editor have no serious accessibility violations", async ({ page }) => {
  await signUp(page);
  await expectAccessible(page, "home");
  for (const route of ["/documents", "/new", "/templates", "/settings/account", "/settings/billing"]) {
    await page.goto(route);
    await expectAccessible(page, route);
  }

  await createDocument(page, { text: "# Report\n\nA paragraph with a [link to the report](https://example.com/report).\n\n- one\n- two" });
  await expectAccessible(page, "editor");
  for (const panel of ["Health", "Review", "Translate", "Settings"]) {
    await openPanel(page, panel);
    await expectAccessible(page, `editor, ${panel} panel`);
  }

  // The 2.0 shell (?editor=2) on the same document, light and dark, with a panel open.
  await page.goto(`${new URL(page.url()).pathname}?editor=2`);
  await expect(page.getByRole("navigation", { name: "Editor panels" })).toBeVisible();
  await expectAccessible(page, "editor 2.0");
  await page.getByRole("button", { name: "Open Templates" }).click();
  await expectAccessible(page, "editor 2.0, Templates panel");
  await page.context().addCookies([{ name: "smartdoc_theme", value: "dark", url: "http://localhost:3100" }]);
  await page.reload();
  await expect(page.getByRole("navigation", { name: "Editor panels" })).toBeVisible();
  await expectAccessible(page, "editor 2.0, dark");
});

test("the Doctor panel (prototype) has no serious accessibility violations, light and dark", async ({ page }) => {
  await signUp(page);
  const id = await createDocument(page, { file: path.join(GOLDEN, "..", "doctor", "d13-mixed-report.docx") });
  for (const theme of ["light", "dark"]) {
    await page.context().addCookies([{ name: "smartdoc_theme", value: theme, url: "http://localhost:3100" }]);
    await page.goto(`/documents/${id}?editor=2&doctor=1`);
    await openPanel(page, "Open Doctor"); // the 2.0 shell remembers the open panel: only opened when it isn't
    await page.getByRole("button", { name: "Check the document" }).click();
    await page.getByRole("region", { name: "Repairs in the Word file" }).getByRole("checkbox").first().check();
    await page.getByRole("button", { name: "Check the repaired file" }).click();
    await expect(page.getByText("Verified: every check passed.")).toBeVisible();
    await expectAccessible(page, `Doctor panel, ${theme}`);
  }
});
