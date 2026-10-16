import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { formatListNumber, levelLabel } from "./listLabels";
import { MORE_FORMATS, moreFormat, WORD_FORMATS } from "./numberFormats";

/**
 * More of Word's number styles (DOCX-016B): each label the one Word shows -- the same labels,
 * read from Word, that the backend's formatter is checked against.
 */
// Numbers in words, by the paragraph's language (DOCX-016C), read from Word too; how far each is spelled here.
const WORDS: Record<string, Record<string, Record<string, string>>> = JSON.parse(
  readFileSync(path.join(process.cwd(), "..", "backend", "tests", "fixtures", "word_number_words.json"), "utf8"),
).labels;
const SPELLED_UP_TO: Record<string, number> = { "en-US": 999_999, "bg-BG": 999 };

const WORD: Record<string, Record<string, string>> = JSON.parse(
  readFileSync(path.join(process.cwd(), "..", "backend", "tests", "fixtures", "word_number_labels.json"), "utf8"),
).labels;

describe("Word's number styles", () => {
  it.each(Object.keys(WORD).sort())("%s: every label is the one Word shows", (format) => {
    const wrong = Object.entries(WORD[format]).filter(([value, label]) => formatListNumber(Number(value), format) !== label);
    expect(wrong).toEqual([]);
  });

  it("checks every style here against Word", () => {
    expect(MORE_FORMATS.filter((format) => !(format in WORD) && !WORD_FORMATS.includes(format))).toEqual([]);
  });

  it.each(WORD_FORMATS.flatMap((format) => Object.keys(SPELLED_UP_TO).map((language) => [format, language])))(
    "%s in %s: numbers in words as Word writes them",
    (format, language) => {
      const wrong = Object.entries(WORDS[format][language]).filter(
        ([value, label]) => Number(value) <= SPELLED_UP_TO[language] && formatListNumber(Number(value), format, language) !== label,
      );
      expect(wrong).toEqual([]);
      expect(formatListNumber(SPELLED_UP_TO[language] + 1, format, language)).toBe(String(SPELLED_UP_TO[language] + 1));
    },
  );

  it("puts any style in a label pattern, and shows a number it has no label for as it is", () => {
    expect(levelLabel("%1.%2", [3, 11], ["ideographDigital", "japaneseCounting"])).toBe("三.十一");
    expect(levelLabel("(%1)", [2], ["ordinal"])).toBe("(2nd)");
    expect(formatListNumber(0, "ordinal")).toBe("0");
    expect(moreFormat(3, "toString")).toBeNull(); // only the styles' own names
  });
});
