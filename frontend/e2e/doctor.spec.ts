import { readFileSync } from "node:fs";
import path from "node:path";
import { inflateRawSync } from "node:zlib";

import { expect, test, type Page } from "@playwright/test";

import { API, createDocument, GOLDEN, PASSWORD, signUp, uniqueEmail } from "./helpers";

/**
 * Document Doctor v0 (prototype) in the 2.0 editor, only with ?doctor=1: check -> choose -> check the repaired
 * file -> download only when verified. A file Doctor refuses says why and offers nothing.
 */

const DOCTOR = path.join(GOLDEN, "..", "doctor");

async function openDoctor(page: Page, id: string) {
  await page.goto(`/documents/${id}?editor=2&doctor=1`);
  await page.getByRole("button", { name: "Open Doctor" }).click();
  await expect(page.getByText("Document Doctor", { exact: true })).toBeVisible();
}

/** word/document.xml of a .docx, read with Node's own zlib (the entry is deflated). */
function documentXml(zip: Buffer): string {
  const name = Buffer.from("word/document.xml");
  let at = 0;
  while ((at = zip.indexOf(Buffer.from([0x50, 0x4b, 0x03, 0x04]), at)) !== -1) {
    const nameLength = zip.readUInt16LE(at + 26);
    const extra = zip.readUInt16LE(at + 28);
    const size = zip.readUInt32LE(at + 18);
    if (zip.subarray(at + 30, at + 30 + nameLength).equals(name)) {
      const start = at + 30 + nameLength + extra;
      return inflateRawSync(zip.subarray(start, start + size)).toString("utf-8");
    }
    at += 4;
  }
  throw new Error("no word/document.xml");
}

test.describe("Document Doctor v0", () => {
  test.beforeEach(async ({ page }) => {
    await signUp(page);
  });

  test("hidden without the flag", async ({ page }) => {
    const id = await createDocument(page, { file: path.join(DOCTOR, "d09-clean.docx") });
    await page.goto(`/documents/${id}?editor=2`);
    await expect(page.getByRole("navigation", { name: "Editor panels" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Open Doctor" })).toHaveCount(0);
  });

  test("check, choose, verify, download: the repaired file has fewer empty paragraphs", async ({ page }) => {
    const id = await createDocument(page, { file: path.join(DOCTOR, "d13-mixed-report.docx") });
    await openDoctor(page, id);
    await page.getByRole("button", { name: "Check the document" }).click();

    const repairs = page.getByRole("region", { name: "Repairs in the Word file" });
    await expect(repairs.getByRole("checkbox")).toHaveCount(2);
    // Nothing is chosen until the person chooses.
    for (const box of await repairs.getByRole("checkbox").all()) await expect(box).not.toBeChecked();
    for (const box of await repairs.getByRole("checkbox").all()) await box.check();

    await page.getByRole("button", { name: "Check the repaired file" }).click();
    await expect(page.getByText("Verified: every check passed.")).toBeVisible();
    for (const name of ["Words", "Everything not repaired", "Valid Word file"]) await expect(page.getByText(name, { exact: true })).toBeVisible();

    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download the repaired file" }).click();
    const file = await download;
    expect(file.suggestedFilename()).toContain("repaired");
    const repaired = readFileSync(await file.path());
    const original = readFileSync(path.join(DOCTOR, "d13-mixed-report.docx"));
    const empties = (xml: string) => (xml.match(/<w:p\/>/g) ?? []).length;
    expect(empties(documentXml(repaired))).toBeLessThan(empties(documentXml(original)));
    expect(documentXml(repaired)).toContain("Quarterly summary");
  });

  test("a signed file is refused, with the reason, and nothing is offered", async ({ page }) => {
    const id = await createDocument(page, { file: path.join(DOCTOR, "d10-signed.docx") });
    await openDoctor(page, id);
    await page.getByRole("button", { name: "Check the document" }).click();
    await expect(page.getByRole("region", { name: "Not repaired automatically" })).toContainText("digitally signed");
    await expect(page.getByRole("button", { name: "Check the repaired file" })).toHaveCount(0);
  });
});

test.describe("in Bulgarian", () => {
  test.use({ locale: "bg-BG" });

  test("the Doctor panel speaks Bulgarian", async ({ page }) => {
    await page.goto("/register");
    await page.getByLabel("Имейл").fill(uniqueEmail("doctor-bg"));
    await page.getByLabel("Парола").fill(PASSWORD);
    await page.getByRole("button", { name: "Създай акаунт" }).click();
    await expect(page.getByRole("heading", { name: /Добре дошли отново/ })).toBeVisible();
    const uploaded = await page.request.post(`${API}/documents/upload`, {
      multipart: { file: { name: "d09-clean.docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: readFileSync(path.join(DOCTOR, "d09-clean.docx")) } },
      headers: { Origin: "http://localhost:3100" },
    });
    const { id } = (await uploaded.json()) as { id: string };
    await page.goto(`/documents/${id}?editor=2&doctor=1`);
    await page.getByRole("button", { name: "Отвори Доктор" }).click();
    await expect(page.getByText("Доктор на документи", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Провери документа" })).toBeVisible();
  });
});
