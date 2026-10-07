import path from "node:path";

import { expect, test } from "@playwright/test";

import { API, createDocument, editor, GOLDEN, signUp } from "./helpers";

/**
 * A Word file's pictures on the pages as Word draws them (tracker DOCX-018, brief
 * §27): one cropped, turned and flipped, with its alt text; one that floats, shown in
 * line with the text; one in a table cell at its own size; and two in a numbered list's
 * items, under their text (DOCX-027).
 */

test("pictures are drawn cropped, turned and at their size", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { file: path.join(GOLDEN, "17-pictures.docx") });

  const pictures = editor(page).locator("img");
  await expect(pictures).toHaveCount(5);
  await expect.poll(() => pictures.evaluateAll((images) => images.every((image) => (image as HTMLImageElement).complete))).toBe(true);

  const turned = pictures.first();
  await expect(turned).toHaveAttribute("alt", "A red and blue flag");
  const look = await turned.evaluate((image) => ({ clip: image.style.clipPath, transform: image.style.transform }));
  expect(look).toEqual({ clip: "inset(0% 0% 0% 25%)", transform: "rotate(90deg) scale(-1, 1)" });
  // Turned by the browser: the whole picture (5.33 by 2 cm, clipped to the 4 cm kept) stands on end ...
  const box = (await turned.boundingBox())!;
  expect(box.height / box.width).toBeCloseTo(8 / 3, 1);
  // ... and takes the room of its turned outline, as in Word: the part kept stands 4 cm high, twice
  // the 2 cm it is wide, and the text below starts below it.
  const above = (await editor(page).getByText("A picture cropped on the left").boundingBox())!;
  const below = (await editor(page).getByText("Text flows around the picture below").boundingBox())!;
  expect(below.y - (above.y + above.height)).toBeGreaterThanOrEqual(2 * box.width - 1);

  const inCell = editor(page).locator("td img");
  await expect(inCell).toHaveCount(1);
  expect(await inCell.evaluate((image) => image.style.width)).toBe("3cm");

  // The list's items hold their pictures: numbered 1 and 2, the second item only its picture.
  const items = editor(page).locator("ol > li");
  await expect(items).toHaveCount(3);
  await expect(items.nth(0).locator("img")).toHaveCount(1);
  await expect(items.nth(1).locator("img")).toHaveCount(1);
  await expect(items.nth(0)).toHaveAttribute("data-label", "1.");
  await expect(items.nth(2)).toHaveAttribute("data-label", "3.");
});

test("a picture text wraps around floats at its side, with the text beside it", async ({ page }) => {
  // DOCX-018A: floating pictures used to be shown in line.
  await signUp(page);
  await createDocument(page, { file: path.join(GOLDEN, "17-pictures.docx") });
  const floating = editor(page).locator("img").nth(1); // "Text flows around the picture below": square wrap, on the left
  await expect(floating).toHaveCSS("float", "left");
  // The wrap is laid out once the picture has loaded and the page settled (editor/floatWrap.ts): measured until then.
  await expect
    .poll(async () => {
      const picture = (await floating.boundingBox())!;
      // Where the text's line is (its paragraph's box stays full width beside a float; its lines move over).
      const beside = await editor(page)
        .getByText("The text beside it.")
        .evaluate((element) => {
          const range = document.createRange();
          range.selectNodeContents(element);
          const box = range.getClientRects()[0];
          return { x: box.x, y: box.y };
        });
      return {
        rightOfIt: beside.x > picture.x + picture.width - 1, // to its right ...
        levelWithIt: beside.y < picture.y + picture.height, // ... and level with it, not below
      };
    })
    .toEqual({ rightOfIt: true, levelWithIt: true });
});

test("a picture is cropped, turned and flipped in the editor, and saved so", async ({ page }) => {
  // DOCX-018B: a picture's crop, turn and flips used to be kept but not changeable here.
  await signUp(page);
  const id = await createDocument(page, { file: path.join(GOLDEN, "17-pictures.docx") });
  const stored = async () => {
    const document = await (await page.request.get(`${API}/documents/${id}`)).json();
    return document.elements.find((element: { type: string }) => element.type === "image").image;
  };
  const before = await stored();
  const picture = editor(page).locator("img").first();
  await picture.click();
  const controls = page.getByRole("group", { name: "Turn and flip" });
  await expect(controls).toBeVisible();

  await controls.getByRole("button", { name: "Turn right" }).click();
  await controls.getByRole("button", { name: "Flip up and down" }).click();
  await expect(controls.getByRole("button", { name: "Flip up and down" })).toHaveAttribute("aria-pressed", "true");
  const cropTop = page.getByRole("group", { name: "Crop" }).getByLabel("Crop top (%)");
  await cropTop.fill("10");
  await cropTop.blur();

  await expect(picture).toHaveCSS("clip-path", /inset\(10%/);
  await expect
    .poll(async () => {
      const image = await stored();
      return [image.rotation, image.flipVertical, image.crop?.top];
    })
    .toEqual([((before.rotation ?? 0) + 90) % 360 || null, !before.flipVertical, 0.1]);

  // Back to the picture as it came.
  await controls.getByRole("button", { name: "Undo crop and turn" }).click();
  await expect.poll(async () => (await stored()).crop).toBeNull();
});
