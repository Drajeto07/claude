import path from "node:path";

import { expect, test } from "@playwright/test";

import { createDocument, editor, GOLDEN, signUp } from "./helpers";

/**
 * A Word file's pictures on the pages as Word draws them (tracker DOCX-018, brief
 * §27): one cropped, turned and flipped, with its alt text; one that floats, shown in
 * line with the text; one in a table cell at its own size.
 */

test("pictures are drawn cropped, turned and at their size", async ({ page }) => {
  await signUp(page);
  await createDocument(page, { file: path.join(GOLDEN, "17-pictures.docx") });

  const pictures = editor(page).locator("img");
  await expect(pictures).toHaveCount(3);
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
});
