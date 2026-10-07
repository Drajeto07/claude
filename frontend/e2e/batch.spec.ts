import { expect, test } from "@playwright/test";

import { API, createDocument, signUp } from "./helpers";

/**
 * Batch formatting (tracker FEAT-001): documents ticked in the list get one template at once, as
 * a batch of format jobs followed in the list until each is done.
 */
test("one template is applied to the documents ticked in the list", async ({ page }) => {
  await signUp(page);
  const first = await createDocument(page, { text: "# Batch one\n\nThe first report." });
  const second = await createDocument(page, { text: "# Batch two\n\nThe second report." });

  await page.goto("/documents");
  await page.getByRole("checkbox", { name: /^Select .*one/ }).check();
  await page.getByRole("checkbox", { name: /^Select .*two/ }).check();
  const bar = page.getByRole("region", { name: "Selected documents" });
  await expect(bar.getByText("2 selected")).toBeVisible();
  await bar.getByLabel("Template").selectOption("academic-default");
  await bar.getByRole("button", { name: "Apply to 2 documents" }).click();
  await expect(bar.getByRole("status")).toContainText("2 of 2 done");

  for (const id of [first, second]) {
    const document = await (await page.request.get(`${API}/documents/${id}`)).json();
    expect(document.templateId).toBe("academic-default");
  }
  await expect(page.getByText("Formatted", { exact: false }).first()).toBeVisible(); // the list's status, refreshed
});
