import { describe, expect, it } from "vitest";

import { fillPageFields } from "./headerFields";

describe("a header's fields on the page (DOCX-020A)", () => {
  it("shows the page number and count, and each other field's last result", () => {
    expect(fillPageFields("{FIELD STYLEREF Heading1|Introduction} - page {PAGE} of {NUMPAGES}", "3", 9)).toBe("Introduction - page 3 of 9");
    expect(fillPageFields("{FIELD DATE|1.10.2026} {FIELD DOCPROPERTY Company|}", "1", 1)).toBe("1.10.2026 ");
  });

  it("leaves text that only looks like a field alone", () => {
    expect(fillPageFields("{FIELD} and {FIELDS x|y}", "1", 1)).toBe("{FIELD} and {FIELDS x|y}");
  });
});
