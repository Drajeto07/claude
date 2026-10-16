import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { createDocument, editor, GOLDEN, signUp } from "./helpers";

/**
 * The page Content-Security-Policy (SEC-020, brief §33): a fresh nonce on every
 * response, no 'unsafe-inline' / 'unsafe-eval' for scripts, every script the page
 * ships carrying that nonce, and the pages, the editor and the template previews
 * working under it with no violation reported by the browser.
 */

function directive(policy: string, name: string): string {
  const found = policy.split(";").map((part) => part.trim()).find((part) => part.startsWith(`${name} `));
  return found ?? "";
}

function nonceOf(policy: string): string {
  const match = /'nonce-([^']+)'/.exec(directive(policy, "script-src"));
  expect(match, "script-src has a nonce").not.toBeNull();
  return match![1];
}

/** Collects every violation the browser reports (the event fires in the page itself). */
async function recordViolations(page: Page) {
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { __cspViolations: string[] }).__cspViolations = seen;
    document.addEventListener("securitypolicyviolation", (event) => {
      seen.push(`${event.violatedDirective} ${event.blockedURI} ${event.sourceFile}:${event.lineNumber}`);
    });
  });
}

const violations = (page: Page) => page.evaluate(() => (window as unknown as { __cspViolations: string[] }).__cspViolations);

test("every page response has its own nonce and a policy without unsafe-inline scripts", async ({ request }) => {
  const first = await request.get("/login");
  const second = await request.get("/login");
  const policy = first.headers()["content-security-policy"];
  const script = directive(policy, "script-src");

  expect(script).toContain("'strict-dynamic'");
  expect(script).not.toContain("'unsafe-inline'");
  expect(script).not.toContain("'unsafe-eval'");
  expect(directive(policy, "style-src")).not.toContain("'unsafe-inline'");
  expect(directive(policy, "connect-src")).toContain("http://localhost:8100");
  expect(directive(policy, "frame-ancestors")).toBe("frame-ancestors 'none'");
  // The other security headers are still sent.
  expect(first.headers()["x-content-type-options"]).toBe("nosniff");
  expect(first.headers()["x-frame-options"]).toBe("DENY");

  expect(nonceOf(second.headers()["content-security-policy"])).not.toBe(nonceOf(policy));

  // Next.js stamped the nonce on every script of the page, inline ones included.
  const html = await first.text();
  const scripts = [...html.matchAll(/<script\b[^>]*>/g)].map((match) => match[0]);
  expect(scripts.length).toBeGreaterThan(0);
  for (const tag of scripts) expect(tag).toContain(`nonce="${nonceOf(policy)}"`);
});

test("the pages, the editor and the template previews run without a policy violation", async ({ page }) => {
  await recordViolations(page);
  const logged: string[] = [];
  page.on("console", (message) => {
    if (/content security policy|refused to/i.test(message.text())) logged.push(message.text());
  });

  await signUp(page);
  await page.goto("/templates");
  await page.getByRole("button", { name: "New template" }).click();
  await page.waitForURL(/\/templates\/[0-9a-f-]{36}$/);
  await expect(page.getByLabel("Name", { exact: true })).toBeVisible();
  expect(await violations(page)).toEqual([]);

  await createDocument(page, { file: path.join(GOLDEN, "16-table-engine.docx") });
  await expect(editor(page).locator(".tableWrapper.word-table").first()).toBeVisible();
  await editor(page).click();
  await page.keyboard.type("typed under the policy");
  await expect(editor(page).getByText("typed under the policy")).toBeVisible();
  expect(await violations(page)).toEqual([]);
  expect(logged).toEqual([]);
});
