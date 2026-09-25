import { describe, expect, it } from "vitest";

import { formatBytes, formatWhen, sourceLabel } from "./format";

describe("formatBytes", () => {
  it.each([
    [512, "512 B"],
    [1536, "1.5 KB"],
    [5 * 1024 * 1024, "5 MB"],
    [250 * 1024 * 1024, "250 MB"],
    [5120 * 1024 * 1024, "5 GB"],
  ])("%d bytes read as %s", (bytes, text) => {
    expect(formatBytes(bytes)).toBe(text);
  });
});

describe("formatWhen", () => {
  const now = new Date("2026-09-25T12:00:00Z");

  it.each([
    ["2026-09-25T11:59:30Z", "just now"],
    ["2026-09-25T11:55:00Z", "5 min ago"],
    ["2026-09-25T09:00:00Z", "3 h ago"],
    ["2026-09-24T10:00:00Z", "yesterday"],
  ])("%s is %s", (iso, text) => {
    expect(formatWhen(iso, now)).toBe(text);
  });

  it("gives the date for anything older", () => {
    expect(formatWhen("2026-09-01T10:00:00Z", now)).toMatch(/2026/);
  });
});

it("names where a document came from", () => {
  expect(sourceLabel("uploaded_docx")).toBe("Word file");
  expect(sourceLabel("something_new")).toBe("Other");
});
