"""Language, script and direction of a text (tracker TRAN-007, brief §95-96), deterministic:
the script from the letters' Unicode ranges (ISO 15924), the direction from the script,
the language from letters only one language of the script uses and its commonest words.
Unsure is said (language None, a low confidence): the user can always set the source
language themselves, and the target is never guessed."""

import re
import unicodedata
from collections import Counter
from functools import lru_cache
from dataclasses import dataclass

# (first, last, ISO 15924)
_RANGES = (
    (0x0041, 0x024F, "Latn"), (0x1E00, 0x1EFF, "Latn"), (0x0370, 0x03FF, "Grek"), (0x1F00, 0x1FFF, "Grek"),
    (0x0400, 0x052F, "Cyrl"), (0x0590, 0x05FF, "Hebr"), (0x0600, 0x06FF, "Arab"), (0x0750, 0x077F, "Arab"),
    (0x0900, 0x097F, "Deva"), (0x0E00, 0x0E7F, "Thai"), (0x3040, 0x30FF, "Kana"), (0x3400, 0x4DBF, "Hani"),
    (0x4E00, 0x9FFF, "Hani"), (0xAC00, 0xD7AF, "Hang"), (0x1100, 0x11FF, "Hang"),
)
RTL_SCRIPTS = frozenset({"Arab", "Hebr"})
_BY_SCRIPT = {"Grek": "el", "Hebr": "he", "Arab": "ar", "Deva": "hi", "Thai": "th", "Hang": "ko"}
_STOPWORDS = {
    "en": "the and of to is in that for with it on are was this be not",
    "de": "der die und das ist nicht mit ein eine zu den von sich auf für",
    "fr": "le la les et des est une pour que dans qui pas sur au du",
    "es": "el la los las y de que en es por una para con no del",
    "it": "il di che e la per non una sono del della gli con le",
    "pt": "o a de que e os em uma para não com do da no se",
    "nl": "de het en van een is niet dat op te met voor zijn",
    "pl": "i w nie na się jest że do to z o jak ale",
    "ro": "și de în este cu care nu pe la o un sunt",
    "tr": "ve bir bu için ile değil da de olan çok",
    "bg": "и на в за да се от с е не са това че като",
    "ru": "и в не на что с это как по он но из то",
    "uk": "і в не на що з це як та до у він",
    "sr": "и у је да се на за са не од",
}
_STOPWORD_SETS = {language: frozenset(words.split()) for language, words in _STOPWORDS.items()}
# Letters only some of a script's languages use.
_CYRILLIC_LETTERS = {"ru": "ыэё", "uk": "іїєґ", "sr": "ђћџљњј", "bg": "ъ"}
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_NAMES = {
    "bg": "Bulgarian", "en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "pt": "Portuguese",
    "nl": "Dutch", "pl": "Polish", "ro": "Romanian", "tr": "Turkish", "ru": "Russian", "uk": "Ukrainian", "sr": "Serbian",
    "el": "Greek", "he": "Hebrew", "ar": "Arabic", "hi": "Hindi", "th": "Thai", "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
}
# The languages a translation can be made into (the UI's list).
TARGET_LANGUAGES = tuple(_NAMES)


@dataclass(frozen=True, slots=True)
class LanguageGuess:
    language: str | None  # BCP 47, None when it can't be told
    script: str | None  # ISO 15924
    direction: str  # "ltr" | "rtl"
    confidence: float


def language_name(tag: str | None) -> str:
    if not tag:
        return "an unknown language"
    return _NAMES.get(tag.split("-")[0].lower(), tag)


def script_of(character: str) -> str | None:
    """A letter's script (ISO 15924: Latn, Cyrl, Arab, Hani, Kana...); None for anything
    common to scripts -- digits, punctuation, spaces, symbols."""
    return _script(character)


# Asked for every character of every run the PDF export draws (FONT-002): a document uses few distinct
# characters, so each is looked up once (TEST-041 caught the export of 500 blocks at +66% without this).
@lru_cache(maxsize=8192)
def _script(character: str) -> str | None:
    code = ord(character)
    for first, last, script in _RANGES:
        if first <= code <= last:
            return script if unicodedata.category(character).startswith("L") else None
    return None


def detect(text: str) -> LanguageGuess:
    letters = Counter(script for character in text if (script := _script(character)) is not None)
    if not letters:
        return LanguageGuess(None, None, "ltr", 0.0)
    script, count = letters.most_common(1)[0]
    share = count / sum(letters.values())
    direction = "rtl" if script in RTL_SCRIPTS else "ltr"
    if script in ("Hani", "Kana"):
        language = "ja" if letters.get("Kana") else "zh"
        return LanguageGuess(language, "Jpan" if language == "ja" else "Hani", "ltr", round(min(0.9, share), 2))
    if script in _BY_SCRIPT:
        return LanguageGuess(_BY_SCRIPT[script], script, direction, round(min(0.9, share), 2))
    words = [word.lower() for word in _WORD.findall(text)]
    candidates = [language for language in _STOPWORDS if (language in ("bg", "ru", "uk", "sr")) == (script == "Cyrl")]
    scores = Counter({language: sum(word in _STOPWORD_SETS[language] for word in words) for language in candidates})
    if script == "Cyrl":
        lowered = text.lower()
        for language, special in _CYRILLIC_LETTERS.items():
            scores[language] += 3 * sum(lowered.count(letter) for letter in special)
    ranked = scores.most_common(2)
    best, best_score = ranked[0] if ranked else (None, 0)
    second = ranked[1][1] if len(ranked) > 1 else 0
    if best is None or best_score < 2 or best_score < 1.5 * second:
        return LanguageGuess(None, script, direction, round(0.3 * share, 2))
    confidence = min(0.95, 0.5 + 0.45 * (best_score - second) / best_score) * share
    return LanguageGuess(best, script, direction, round(confidence, 2))
