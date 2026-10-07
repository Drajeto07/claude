"""Word's number styles past 1, a, i (tracker DOCX-016B): the label each shows for a number, as
Word itself shows it -- checked against Word's own labels (tests/fixtures/word_number_labels.json,
read from Word for every style here). editor/numberFormats.ts mirrors this.

Numbers spelled in words (cardinalText "One", ordinalText "First", DOCX-016C) are in the list's
language, as Word writes them: English up to 999,999 and Bulgarian up to 999 as Word does, its
oddities and all (100 is "Стои"), checked against tests/fixtures/word_number_words.json; another
language, or a number past those, is shown as it is. Not here: hindiCounting, thaiCounting and
vietnameseCounting -- numbered 1, 2, 3 and reported. A number a style has no label for is shown
as it is."""

from __future__ import annotations

from collections.abc import Callable, Sequence

# --- letters that run through an alphabet -------------------------------------------------------
# Word's Cyrillic letters (russianLower): а..я without ё, й, ъ, ь -- ы is one (Word numbers 26 ы, 27 э).
CYRILLIC = "абвгдежзиклмнопрстуфхцчшщыэюя"


def _split(letters: str) -> list[str]:
    return letters.split(" ")


# Each a, b .. z, then aa, bb ..: the letter, written once more each time round.
_DOUBLING: dict[str, list[str]] = {
    "hindiVowels": _split("क ख ग घ ङ च छ ज झ ञ ट ठ ड ढ ण त थ द ध न ऩ प फ ब भ म य र ऱ ल ळ ऴ व श ष स ह"),
    "hindiConsonants": _split("अ आ इ ई उ ऊ ऋ ऌ ऍ ऎ ए ऐ ऑ ऒ ओ औ अं अः"),
    "thaiLetters": _split("ก ข ค ง จ ฉ ช ซ ฌ ญ ฎ ฏ ฐ ฑ ฒ ณ ด ต ถ ท ธ น บ ป ผ ฝ พ ฟ ภ ม ย ร ล ว ศ ษ ส ห ฬ อ ฮ"),
    # Arabic letters with a zero-width non-joiner after each (alphabetical) or before each (abjad order), as Word writes them.
    "arabicAlpha": [letter + "‌" for letter in "أبتثجحخدذرزسشصضطظعغفقكلمنهوي"],
    "arabicAbjad": ["‌" + letter for letter in "أبجدهوزحطيكلمنسعفصقرشتثخذضظغ"],
}
# Each a .. z, then a again.
_CYCLING: dict[str, str | list[str]] = {
    "aiueo": "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜｦﾝ",
    "aiueoFullWidth": "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン",
    "iroha": "ｲﾛﾊﾆﾎﾍﾄﾁﾘﾇﾙｦﾜｶﾖﾀﾚｿﾂﾈﾅﾗﾑｳヰﾉｵｸﾔﾏｹﾌｺｴﾃｱｻｷﾕﾒﾐｼヱﾋﾓｾｽﾝ",
    "irohaFullWidth": "イロハニホヘトチリヌルヲワカヨタレソツネナラムウヰノオクヤマケフコエテアサキユメミシヱヒモセスン",
    "ganada": "가나다라마바사아자차카타파하",
    "chosung": "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ",
}
# Only so many: one character each from 1, otherwise the number as it is.
_UP_TO: dict[str, str] = {
    "decimalEnclosedCircle": "".join(chr(0x2460 + index) for index in range(20)),  # ① .. ⑳
    "decimalEnclosedParen": "".join(chr(0x2474 + index) for index in range(20)),  # ⑴ .. ⒇
    "decimalEnclosedFullstop": "".join(chr(0x2488 + index) for index in range(20)),  # ⒈ .. ⒛
    "decimalEnclosedCircleChinese": "".join(chr(0x2460 + index) for index in range(10)),  # ① .. ⑩
    "ideographTraditional": "甲乙丙丁戊己庚辛壬癸",
    "ideographZodiac": "子丑寅卯辰巳午未申酉戍亥",  # Word's 11th is 戍, not 戌
}
# Digits of another script, one for one.
_DIGITS: dict[str, str] = {
    "decimalFullWidth": "０１２３４５６７８９",
    "hindiNumbers": "०१२३४५६७८९",
    "thaiNumbers": "๐๑๒๓๔๕๖๗๘๙",
    "ideographDigital": "〇一二三四五六七八九",
    "japaneseDigitalTenThousand": "〇一二三四五六七八九",
    "koreanDigital": "영일이삼사오육칠팔구",
}
_CHICAGO = "*†‡§"
_HAN = "〇一二三四五六七八九"


def _doubling(letters: Sequence[str], value: int) -> str:
    return letters[(value - 1) % len(letters)] * ((value - 1) // len(letters) + 1)


def _ordinal(value: int) -> str:
    suffix = "th" if value % 100 in (11, 12, 13) else {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _hebrew(value: int) -> str:
    """Hebrew numerals (hebrew1): ק ר ש for hundreds, י .. צ for tens, א .. ט for units, 15 and 16
    as ט+ו and ט+ז. Word counts them up to 392 and then from 1 again."""
    value = (value - 1) % 392 + 1
    hundreds, rest = divmod(value, 100)
    tens, units = divmod(rest, 10)
    head = "קרש"[hundreds - 1] if hundreds else ""
    if rest in (15, 16):
        return head + "ט" + ("ו" if rest == 15 else "ז")
    return head + ("יכלמנסעפצ"[tens - 1] if tens else "") + ("אבגדהוזחט"[units - 1] if units else "")


def _hebrew_letters(value: int) -> str:
    """Hebrew letters (hebrew2): א .. ת, then ת and the next letter again: תא, תב .. תת, תתא --
    after a right-to-left mark, as Word writes it."""
    letters = "אבגדהוזחטיכלמנסעפצקרשת"
    fulls, rest = divmod(value - 1, 22)
    return "‏" + "ת" * fulls + letters[rest]


def _counting(value: int, digits: str, units: str, *, one_before: str = "") -> str:
    """A number in East Asian counting under 10,000: each digit and its unit (十 百 千), a 1 before a
    unit written only for the units in `one_before`."""
    text = ""
    for power, unit in ((1000, units[2]), (100, units[1]), (10, units[0])):
        digit, value = divmod(value, power)
        if digit:
            text += ("" if digit == 1 and unit not in one_before else digits[digit]) + unit
    return text + (digits[value] if value else "")


def _japanese(value: int) -> str:
    """japaneseCounting: 一 .. 十, 十一, 二十, 百, 百一, 千二百三十四, then 一万, 十万."""
    high, low = divmod(value, 10000)
    if high and high < 10000:
        return _counting(high, _HAN, "十百千") + "万" + _counting(low, _HAN, "十百千")
    return _counting(value, _HAN, "十百千")


def _korean(value: int) -> str:
    """koreanCounting: 일 .. 십, 십일, 이십, 백, 천, then 만, 십만 -- no 일 before a unit."""
    digits = "영일이삼사오육칠팔구"
    high, low = divmod(value, 10000)
    if high and high < 10000:
        return ("" if high == 1 else _counting(high, digits, "십백천")) + "만" + _counting(low, digits, "십백천")
    return _counting(value, digits, "십백천")


def _chinese(value: int) -> str:
    """chineseCounting and taiwaneseCounting: counted up to 99 (十, 十一, 二十一), from 100 digit
    by digit with ○ for nought, as Word shows them."""
    if value < 100:
        return _counting(value, _HAN, "十百千")
    return "".join("一二三四五六七八九"[int(digit) - 1] if digit != "0" else "○" for digit in str(value))


def _chinese_thousand(value: int, digits: str = _HAN, units: str = "十百千", ten_thousand: str = "万", nought: str = "〇", one_ten: bool = False) -> str:
    """chineseCountingThousand (and, with its own characters, chineseLegalSimplified): counted with
    十 百 千 万; a 1 before 十 except in 10-19 alone; one nought for a gap (一百〇一, 一千〇一)."""

    def under(value: int, lead: bool) -> str:
        text, gap = "", False
        for power, unit in ((1000, units[2]), (100, units[1]), (10, units[0]), (1, "")):
            digit, value = divmod(value, power)
            if digit:
                if gap and text:
                    text += nought
                one_dropped = power == 10 and digit == 1 and lead and not text and not one_ten
                text += ("" if one_dropped else digits[digit]) + unit
                gap = False
            elif text:
                gap = True
        return text

    high, low = divmod(value, 10000)
    if high and high < 10000:
        return under(high, False) + ten_thousand + ((nought if low < 1000 else "") + under(low, False) if low else "")
    return under(value, True)


def _legal_simplified(value: int) -> str:
    return _chinese_thousand(value, "零壹贰叁肆伍陆柒捌玖", "拾佰仟", "萬", "零", one_ten=True)


FORMATTERS: dict[str, Callable[[int], str]] = {
    "ordinal": _ordinal,
    "hex": lambda value: f"{value:X}",
    "chicago": lambda value: _doubling(_CHICAGO, value),
    "hebrew1": _hebrew,
    "hebrew2": _hebrew_letters,
    "japaneseCounting": _japanese,
    "koreanCounting": _korean,
    "chineseCounting": _chinese,
    "taiwaneseCounting": _chinese,
    "chineseCountingThousand": _chinese_thousand,
    "chineseLegalSimplified": _legal_simplified,
    "numberInDash": lambda value: f"- {value} -",
    "decimalHalfWidth": str,
    **{name: (lambda letters: lambda value: _doubling(letters, value))(letters) for name, letters in _DOUBLING.items()},
    **{name: (lambda letters: lambda value: letters[(value - 1) % len(letters)])(letters) for name, letters in _CYCLING.items()},
    **{name: (lambda letters: lambda value: letters[value - 1] if value <= len(letters) else str(value))(letters) for name, letters in _UP_TO.items()},
    **{name: (lambda digits: lambda value: "".join(digits[int(digit)] for digit in str(value)))(digits) for name, digits in _DIGITS.items()},
}
# --- numbers spelled in words, in the list's language (DOCX-016C) ---------------------------------
WORD_FORMATS = ("cardinalText", "ordinalText")

_EN_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_EN_ORDINAL = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}


def _en_under_thousand(value: int) -> str:
    hundreds, rest = divmod(value, 100)
    words = [f"{_EN_ONES[hundreds]} hundred"] if hundreds else []
    if rest:
        tens, units = divmod(rest, 10)
        words.append(_EN_ONES[rest] if rest < 20 else _EN_TENS[tens] + (f"-{_EN_ONES[units]}" if units else ""))
    return " ".join(words)


def _english(value: int, ordinal: bool) -> str | None:
    """One, Twenty-one, One hundred one, Two thousand twenty-four; First, Twelfth, Twentieth."""
    if not 0 < value < 1_000_000:
        return None
    thousands, rest = divmod(value, 1000)
    text = " ".join(part for part in (f"{_en_under_thousand(thousands)} thousand" if thousands else "", _en_under_thousand(rest)) if part)
    if ordinal:
        head, cut, last = max(text.rpartition(" "), text.rpartition("-"), key=lambda parts: len(parts[0]))
        last = _EN_ORDINAL.get(last) or (last[:-1] + "ieth" if last.endswith("y") else last + "th")
        text = head + cut + last
    return text[0].upper() + text[1:]


_BG_UNITS = ["", "един", "два", "три", "четири", "пет", "шест", "седем", "осем", "девет", "десет"]
_BG_TEENS = ["", "единадесет", "дванадесет", "тринадесет", "четиринадесет", "петнадесет", "шестнадесет", "седемнадесет", "осемнадесет", "деветнадесет"]
_BG_TENS = ["", "десет", "двадесет", "тридесет", "четиридесет", "петдесет", "шестдесет", "седемдесет", "осемдесет", "деветдесет"]
_BG_HUNDREDS = ["", "сто", "двеста", "триста", "четиристотин", "петстотин", "шестстотин", "седемстотин", "осемстотин", "деветстотин"]
_BG_UNITS_ORDINAL = ["", "първият", "вторият", "третият", "четвъртият", "петият", "шестият", "седмият", "осмият", "деветият", "десетият"]
_BG_HUNDREDS_ORDINAL = ["", *(f"{stem}стотеният" for stem in ("", "две", "три", "четири", "пет", "шест", "седем", "осем", "девет"))]


def _bg_under_hundred(value: int, ordinal: bool) -> str:
    if value <= 10:
        return (_BG_UNITS_ORDINAL if ordinal else _BG_UNITS)[value]
    if value < 20:
        return _BG_TEENS[value - 10] + ("ият" if ordinal else "")
    tens, units = divmod(value, 10)
    if not units:
        return _BG_TENS[tens] + ("ият" if ordinal else "")
    return f"{_BG_TENS[tens]} и {(_BG_UNITS_ORDINAL if ordinal else _BG_UNITS)[units]}"


def _bulgarian(value: int, ordinal: bool) -> str | None:
    """Word's Bulgarian, as it writes it, up to 999: Един, Двадесет и един, Сто и десет, Сто
    единадесет, Сто двадесет и един -- and a round hundred as "Стои", "Двестаи" (Word's own); Първият,
    Сто и вторият, Стотеният."""
    if not 0 < value < 1000:
        return None
    hundreds, rest = divmod(value, 100)
    if not hundreds:
        text = _bg_under_hundred(rest, ordinal)
    elif not rest:
        text = _BG_HUNDREDS_ORDINAL[hundreds] if ordinal else _BG_HUNDREDS[hundreds] + "и"
    elif ordinal or rest <= 10 or (rest < 100 and rest % 10 == 0):
        text = f"{_BG_HUNDREDS[hundreds]} и {_bg_under_hundred(rest, ordinal)}"
    else:
        text = f"{_BG_HUNDREDS[hundreds]} {_bg_under_hundred(rest, ordinal)}"
    return text[0].upper() + text[1:]


_SPELLERS = {"en": _english, "bg": _bulgarian}


def spelled(value: int, fmt: str, language: str | None) -> str | None:
    """`value` in words in the language (English when none is known), or None when it can't be."""
    speller = _SPELLERS.get((language or "en").split("-")[0].lower())
    return speller(value, fmt == "ordinalText") if speller is not None else None


def words_language_known(language: str | None) -> bool:
    """Whether numbers in words can be spelled in this language here (English, Bulgarian)."""
    return (language or "en").split("-")[0].lower() in _SPELLERS


# The styles here, which a list may now have (besides decimal, letters, Roman, 01 and а б в).
MORE_FORMATS = (*FORMATTERS, *WORD_FORMATS)
# How far each style counts like Word: past this Word starts some again (Hebrew numerals from 392,
# its digits for ten-thousands) or shows nothing -- lists don't get there.
MAX_LIKE_WORD = 9999


def more_format(value: int, fmt: str, language: str | None = None) -> str | None:
    """`value` in one of the styles here, or None when it isn't one (or the number is 0 or less, or
    a number in words this language or this size can't spell)."""
    if fmt in WORD_FORMATS:
        return spelled(value, fmt, language) if value > 0 else None
    formatter = FORMATTERS.get(fmt)
    return formatter(value) if formatter is not None and value > 0 else None
