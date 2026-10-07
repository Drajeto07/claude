/**
 * Word's number styles past 1, a, i (tracker DOCX-016B): the label each shows for a number, as
 * Word itself shows it. Mirrors the backend's app/formatting/number_formats.py; both are checked
 * against Word's own labels (backend/tests/fixtures/word_number_labels.json).
 *
 * Numbers spelled in words (cardinalText, ordinalText: DOCX-016C) are in the list's language, as
 * Word writes them: English up to 999,999, Bulgarian up to 999, Word's oddities and all; another
 * language, or a number past those, is shown as it is. A number a style has no label for is shown
 * as it is.
 */

// Word's Cyrillic letters (russianLower): а..я without ё, й, ъ, ь -- ы is one (26 ы, 27 э).
export const CYRILLIC = "абвгдежзиклмнопрстуфхцчшщыэюя";

const split = (letters: string) => letters.split(" ");
const range = (first: number, count: number) => Array.from({ length: count }, (_, index) => String.fromCodePoint(first + index)).join("");

// Each a, b .. z, then aa, bb ..: the letter, written once more each time round.
const DOUBLING: Record<string, string[]> = {
  hindiVowels: split("क ख ग घ ङ च छ ज झ ञ ट ठ ड ढ ण त थ द ध न ऩ प फ ब भ म य र ऱ ल ळ ऴ व श ष स ह"),
  hindiConsonants: split("अ आ इ ई उ ऊ ऋ ऌ ऍ ऎ ए ऐ ऑ ऒ ओ औ अं अः"),
  thaiLetters: split("ก ข ค ง จ ฉ ช ซ ฌ ญ ฎ ฏ ฐ ฑ ฒ ณ ด ต ถ ท ธ น บ ป ผ ฝ พ ฟ ภ ม ย ร ล ว ศ ษ ส ห ฬ อ ฮ"),
  // Arabic letters with a zero-width non-joiner after each (alphabetical) or before each (abjad order), as Word writes them.
  arabicAlpha: [..."أبتثجحخدذرزسشصضطظعغفقكلمنهوي"].map((letter) => letter + "‌"),
  arabicAbjad: [..."أبجدهوزحطيكلمنسعفصقرشتثخذضظغ"].map((letter) => "‌" + letter),
  chicago: [..."*†‡§"],
};
// Each a .. z, then a again.
const CYCLING: Record<string, string> = {
  aiueo: "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜｦﾝ",
  aiueoFullWidth: "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン",
  iroha: "ｲﾛﾊﾆﾎﾍﾄﾁﾘﾇﾙｦﾜｶﾖﾀﾚｿﾂﾈﾅﾗﾑｳヰﾉｵｸﾔﾏｹﾌｺｴﾃｱｻｷﾕﾒﾐｼヱﾋﾓｾｽﾝ",
  irohaFullWidth: "イロハニホヘトチリヌルヲワカヨタレソツネナラムウヰノオクヤマケフコエテアサキユメミシヱヒモセスン",
  ganada: "가나다라마바사아자차카타파하",
  chosung: "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ",
};
// Only so many: one character each from 1, otherwise the number as it is.
const UP_TO: Record<string, string> = {
  decimalEnclosedCircle: range(0x2460, 20), // ① .. ⑳
  decimalEnclosedParen: range(0x2474, 20), // ⑴ .. ⒇
  decimalEnclosedFullstop: range(0x2488, 20), // ⒈ .. ⒛
  decimalEnclosedCircleChinese: range(0x2460, 10), // ① .. ⑩
  ideographTraditional: "甲乙丙丁戊己庚辛壬癸",
  ideographZodiac: "子丑寅卯辰巳午未申酉戍亥", // Word's 11th is 戍, not 戌
};
// Digits of another script, one for one.
const DIGITS: Record<string, string> = {
  decimalFullWidth: "０１２３４５６７８９",
  hindiNumbers: "०१२३४५६७८९",
  thaiNumbers: "๐๑๒๓๔๕๖๗๘๙",
  ideographDigital: "〇一二三四五六七八九",
  japaneseDigitalTenThousand: "〇一二三四五六七八九",
  koreanDigital: "영일이삼사오육칠팔구",
};
const HAN = "〇一二三四五六七八九";

const doubling = (letters: string[], value: number) => letters[(value - 1) % letters.length].repeat(Math.floor((value - 1) / letters.length) + 1);

function ordinal(value: number): string {
  const suffix = [11, 12, 13].includes(value % 100) ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[value % 10] ?? "th";
  return `${value}${suffix}`;
}

/** Hebrew numerals (hebrew1): Word counts them up to 392 and then from 1 again. */
function hebrew(value: number): string {
  value = ((value - 1) % 392) + 1;
  const hundreds = Math.floor(value / 100);
  const rest = value % 100;
  const head = hundreds ? "קרש"[hundreds - 1] : "";
  if (rest === 15 || rest === 16) return head + "ט" + (rest === 15 ? "ו" : "ז");
  const tens = Math.floor(rest / 10);
  const units = rest % 10;
  return head + (tens ? "יכלמנסעפצ"[tens - 1] : "") + (units ? "אבגדהוזחט"[units - 1] : "");
}

/** Hebrew letters (hebrew2): א .. ת, then תא, תב .. -- after a right-to-left mark, as Word writes it. */
function hebrewLetters(value: number): string {
  const letters = "אבגדהוזחטיכלמנסעפצקרשת";
  return "‏" + "ת".repeat(Math.floor((value - 1) / 22)) + letters[(value - 1) % 22];
}

/** East Asian counting under 10,000: each digit and its unit, a 1 before a unit only for those in `oneBefore`. */
function counting(value: number, digits: string, units: string, oneBefore = ""): string {
  let text = "";
  for (const [power, unit] of [[1000, units[2]], [100, units[1]], [10, units[0]]] as [number, string][]) {
    const digit = Math.floor(value / power);
    value %= power;
    if (digit) text += (digit === 1 && !oneBefore.includes(unit) ? "" : digits[digit]) + unit;
  }
  return text + (value ? digits[value] : "");
}

function japanese(value: number): string {
  const high = Math.floor(value / 10000);
  if (high && high < 10000) return counting(high, HAN, "十百千") + "万" + counting(value % 10000, HAN, "十百千");
  return counting(value, HAN, "十百千");
}

function korean(value: number): string {
  const digits = "영일이삼사오육칠팔구";
  const high = Math.floor(value / 10000);
  if (high && high < 10000) return (high === 1 ? "" : counting(high, digits, "십백천")) + "만" + counting(value % 10000, digits, "십백천");
  return counting(value, digits, "십백천");
}

/** chineseCounting and taiwaneseCounting: counted up to 99, from 100 digit by digit with ○ for nought. */
function chinese(value: number): string {
  if (value < 100) return counting(value, HAN, "十百千");
  return [...String(value)].map((digit) => (digit === "0" ? "○" : "一二三四五六七八九"[Number(digit) - 1])).join("");
}

/** chineseCountingThousand (and chineseLegalSimplified): 十 百 千 万, a 1 before 十 except in 10-19 alone, one nought for a gap. */
function chineseThousand(value: number, digits = HAN, units = "十百千", tenThousand = "万", nought = "〇", oneTen = false): string {
  const under = (value: number, lead: boolean) => {
    let text = "";
    let gap = false;
    for (const [power, unit] of [[1000, units[2]], [100, units[1]], [10, units[0]], [1, ""]] as [number, string][]) {
      const digit = Math.floor(value / power);
      value %= power;
      if (digit) {
        if (gap && text) text += nought;
        const oneDropped = power === 10 && digit === 1 && lead && !text && !oneTen;
        text += (oneDropped ? "" : digits[digit]) + unit;
        gap = false;
      } else if (text) {
        gap = true;
      }
    }
    return text;
  };
  const high = Math.floor(value / 10000);
  const low = value % 10000;
  if (high && high < 10000) return under(high, false) + tenThousand + (low ? (low < 1000 ? nought : "") + under(low, false) : "");
  return under(value, true);
}

const FORMATTERS: Record<string, (value: number) => string> = {
  ordinal,
  hex: (value) => value.toString(16).toUpperCase(),
  hebrew1: hebrew,
  hebrew2: hebrewLetters,
  japaneseCounting: japanese,
  koreanCounting: korean,
  chineseCounting: chinese,
  taiwaneseCounting: chinese,
  chineseCountingThousand: (value) => chineseThousand(value),
  chineseLegalSimplified: (value) => chineseThousand(value, "零壹贰叁肆伍陆柒捌玖", "拾佰仟", "萬", "零", true),
  numberInDash: (value) => `- ${value} -`,
  decimalHalfWidth: String,
  ...Object.fromEntries(Object.entries(DOUBLING).map(([name, letters]) => [name, (value: number) => doubling(letters, value)])),
  ...Object.fromEntries(Object.entries(CYCLING).map(([name, letters]) => [name, (value: number) => [...letters][(value - 1) % [...letters].length]])),
  ...Object.fromEntries(
    Object.entries(UP_TO).map(([name, letters]) => [name, (value: number) => (value <= [...letters].length ? [...letters][value - 1] : String(value))]),
  ),
  ...Object.fromEntries(Object.entries(DIGITS).map(([name, digits]) => [name, (value: number) => [...String(value)].map((digit) => digits[Number(digit)]).join("")])),
};

// --- numbers spelled in words, in the list's language (DOCX-016C) ---------------------------------
export const WORD_FORMATS = ["cardinalText", "ordinalText"];

const EN_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(" ");
const EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];
const EN_ORDINAL: Record<string, string> = { one: "first", two: "second", three: "third", five: "fifth", eight: "eighth", nine: "ninth", twelve: "twelfth" };
const capitalized = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

function enUnderThousand(value: number): string {
  const hundreds = Math.floor(value / 100);
  const rest = value % 100;
  const words = hundreds ? [`${EN_ONES[hundreds]} hundred`] : [];
  if (rest) words.push(rest < 20 ? EN_ONES[rest] : EN_TENS[Math.floor(rest / 10)] + (rest % 10 ? `-${EN_ONES[rest % 10]}` : ""));
  return words.join(" ");
}

/** One, Twenty-one, One hundred one; First, Twelfth, Twentieth -- up to 999,999. */
function english(value: number, ordinal: boolean): string | null {
  if (value <= 0 || value >= 1_000_000) return null;
  const thousands = Math.floor(value / 1000);
  let text = [thousands ? `${enUnderThousand(thousands)} thousand` : "", enUnderThousand(value % 1000)].filter(Boolean).join(" ");
  if (ordinal) {
    const cut = Math.max(text.lastIndexOf(" "), text.lastIndexOf("-"));
    const last = text.slice(cut + 1);
    text = text.slice(0, cut + 1) + (EN_ORDINAL[last] ?? (last.endsWith("y") ? `${last.slice(0, -1)}ieth` : `${last}th`));
  }
  return capitalized(text);
}

const BG_UNITS = ["", "един", "два", "три", "четири", "пет", "шест", "седем", "осем", "девет", "десет"];
const BG_TEENS = ["", "единадесет", "дванадесет", "тринадесет", "четиринадесет", "петнадесет", "шестнадесет", "седемнадесет", "осемнадесет", "деветнадесет"];
const BG_TENS = ["", "десет", "двадесет", "тридесет", "четиридесет", "петдесет", "шестдесет", "седемдесет", "осемдесет", "деветдесет"];
const BG_HUNDREDS = ["", "сто", "двеста", "триста", "четиристотин", "петстотин", "шестстотин", "седемстотин", "осемстотин", "деветстотин"];
const BG_UNITS_ORDINAL = ["", "първият", "вторият", "третият", "четвъртият", "петият", "шестият", "седмият", "осмият", "деветият", "десетият"];
const BG_HUNDREDS_ORDINAL = ["", ...["", "две", "три", "четири", "пет", "шест", "седем", "осем", "девет"].map((stem) => `${stem}стотеният`)];

function bgUnderHundred(value: number, ordinal: boolean): string {
  if (value <= 10) return (ordinal ? BG_UNITS_ORDINAL : BG_UNITS)[value];
  if (value < 20) return BG_TEENS[value - 10] + (ordinal ? "ият" : "");
  const tens = Math.floor(value / 10);
  const units = value % 10;
  if (!units) return BG_TENS[tens] + (ordinal ? "ият" : "");
  return `${BG_TENS[tens]} и ${(ordinal ? BG_UNITS_ORDINAL : BG_UNITS)[units]}`;
}

/** Word's Bulgarian, as it writes it, up to 999 -- a round hundred "Стои", "Двестаи" (Word's own). */
function bulgarian(value: number, ordinal: boolean): string | null {
  if (value <= 0 || value >= 1000) return null;
  const hundreds = Math.floor(value / 100);
  const rest = value % 100;
  let text: string;
  if (!hundreds) text = bgUnderHundred(rest, ordinal);
  else if (!rest) text = ordinal ? BG_HUNDREDS_ORDINAL[hundreds] : `${BG_HUNDREDS[hundreds]}и`;
  else if (ordinal || rest <= 10 || rest % 10 === 0) text = `${BG_HUNDREDS[hundreds]} и ${bgUnderHundred(rest, ordinal)}`;
  else text = `${BG_HUNDREDS[hundreds]} ${bgUnderHundred(rest, ordinal)}`;
  return capitalized(text);
}

const SPELLERS: Record<string, (value: number, ordinal: boolean) => string | null> = { en: english, bg: bulgarian };

/** `value` in words in the language (English when none is known), or null when it can't be. */
export function spelled(value: number, format: string, language: string | null | undefined): string | null {
  const key = (language ?? "en").split("-")[0].toLowerCase();
  if (!Object.prototype.hasOwnProperty.call(SPELLERS, key)) return null;
  return SPELLERS[key](value, format === "ordinalText");
}

export const MORE_FORMATS = [...Object.keys(FORMATTERS), ...WORD_FORMATS];

/** `value` in one of the styles here, or null when it isn't one (or the number is 0 or less, or a
 * number in words this language or this size can't spell). */
export function moreFormat(value: number, format: string, language?: string | null): string | null {
  if (value <= 0) return null;
  if (WORD_FORMATS.includes(format)) return spelled(value, format, language);
  // Its own key only: never "toString" or another an object inherits.
  if (!Object.prototype.hasOwnProperty.call(FORMATTERS, format)) return null;
  return FORMATTERS[format](value);
}
