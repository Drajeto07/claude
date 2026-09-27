import path from "node:path";
import { inflateRawSync } from "node:zlib";

import { expect, test } from "@playwright/test";

import { createDocument, editor, GOLDEN, signUp, waitUntilSaved } from "./helpers";

/**
 * A Word file edited in the app keeps, in the paragraphs nobody touched, what the
 * app doesn't show -- a content control, a double underline, a landscape section
 * (tracker DOCX-028). The Word export copies a block as it is only while the
 * editor has given it back exactly as it was imported, so this is the editor's
 * round trip checked against the server's fingerprints.
 */

const API = "http://localhost:8100/api/v1";

/** One file out of a ZIP (a .docx is one), read with Node's own zlib. */
function unzipped(zip: Buffer, name: string): string {
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

test("a Word file's untouched paragraphs keep what the app doesn't show", async ({ page }) => {
  await signUp(page);
  const id = await createDocument(page, { file: path.join(GOLDEN, "13-kept-blocks.docx") });

  await editor(page).getByText("Edit this line.").click();
  await page.keyboard.press("End");
  const saved = page.waitForResponse(
    (response) =>
      response.url().endsWith("/content") &&
      response.request().method() === "PUT" &&
      response.ok() &&
      (response.request().postData() ?? "").includes("Changed in the app."),
  );
  await page.keyboard.type(" Changed in the app.");
  await saved;
  await waitUntilSaved(page);

  const exported = await page.request.get(`${API}/documents/${id}/export/docx`);
  expect(exported.ok()).toBeTruthy();
  const body = unzipped(await exported.body(), "word/document.xml");

  expect(body).toContain("Edit this line. Changed in the app."); // the edited paragraph, written anew
  expect(body).toContain('<w:alias w:val="Status"/>'); // the content control, which only a copy keeps
  expect(body).toContain('<w:u w:val="double"/>'); // the double underline, likewise
  expect(body).toContain("AUTHOR"); // the field's code
  expect(body.match(/<w:sectPr/g)).toHaveLength(2); // the landscape section before the portrait one
  expect(body).toContain('w:orient="landscape"');
});
