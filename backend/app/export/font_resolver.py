"""Which font draws which part of a text (tracker FONT-002, brief §50, §52): deterministic, never
the AI's choice. The text is split into runs by script (ISO 15924; digits, punctuation and
spaces go with the run around them); each run is drawn by the paragraph's own font when that
font has every character of it, else by the first installed, embeddable font of the script's
fallback chain that has them all (font_catalogue.py). A character no chosen font has -- a
symbol, an emoji -- goes to a font that has it; with none, it is missing, and said so.

A document mixing German, English, Bulgarian and Arabic is drawn in as many fonts as it needs,
not one font for all."""

from dataclasses import dataclass
from functools import lru_cache

from app.export.font_catalogue import CatalogueFont, catalogue, covering
from app.export.fonts import resolved_family
from app.translation.language import RTL_SCRIPTS, script_of

# Scripts whose letters change shape with what is around them: drawn shaped (HarfBuzz).
SHAPED_SCRIPTS = frozenset({"Arab", "Hebr", "Deva", "Thai"})
# Fonts with many symbols, for characters a text's own fonts don't have.
_SYMBOL_FAMILIES = ("Segoe UI Symbol", "DejaVu Sans", "Segoe UI", "Arial", "Microsoft YaHei")


@dataclass(frozen=True, slots=True)
class FontRun:
    text: str
    family: str | None  # None: no installed font draws it
    script: str | None
    direction: str  # "ltr" | "rtl"
    missing: str = ""  # characters nothing installed draws


def script_runs(text: str) -> list[tuple[str, str | None]]:
    """The text in runs of one script; common characters join the run they are in."""
    runs: list[list] = []
    for character in text:
        script = script_of(character)
        if runs and (script is None or runs[-1][1] in (None, script)):
            runs[-1][0] += character
            if runs[-1][1] is None:
                runs[-1][1] = script
        else:
            runs.append([character, script])
    return [(run, script) for run, script in runs]


@lru_cache(maxsize=4096)
def _symbol_font(character: str) -> str | None:
    fonts = catalogue()
    for family in _SYMBOL_FAMILIES:
        font = fonts.get(family)
        if font is not None and font.embeddable and font.draws(character):
            return family
    return next((font.family for font in fonts.values() if font.embeddable and font.draws(character)), None)


def _run_font(preferred: CatalogueFont | None, script: str | None, text: str) -> CatalogueFont | None:
    """The font for a run, chosen by its letters: its symbols, if the font lacks them, are
    drawn by a symbol font character by character."""
    letters = "".join(character for character in text if script_of(character) is not None)
    if preferred is not None and preferred.draws(letters):
        return preferred
    if script is not None:
        drawing = [font for font in covering(script) if font.draws(letters)]
        if drawing:
            return drawing[0]
        candidates = covering(script)
        if candidates:  # none has every letter: the one that has the most
            return max(candidates, key=lambda font: sum(ord(character) in font.characters for character in letters))
    return preferred


def resolve(text: str, family: str | None) -> list[FontRun]:
    """The text in runs, each with the font that draws it (see the module's docstring)."""
    fonts = catalogue()
    preferred_family = resolved_family(family)
    preferred = fonts.get(preferred_family or "")
    # The usual case, at a glance over the distinct characters: the paragraph's font draws them all
    # and they are of one script -- one run, as the full walk below would make (TEST-041).
    characters = set(text)
    if preferred is not None and all(character.isspace() or ord(character) in preferred.characters for character in characters):
        scripts = {script for character in characters if (script := script_of(character)) is not None}
        if len(scripts) <= 1:
            script = next(iter(scripts), None)
            return [FontRun(text, preferred.family, script, "rtl" if script in RTL_SCRIPTS else "ltr")] if text else []
    result: list[FontRun] = []
    for run, script in script_runs(text):
        chosen = _run_font(preferred, script, run)
        direction = "rtl" if script in RTL_SCRIPTS else "ltr"
        piece, piece_family, missing = "", chosen.family if chosen else preferred_family, ""
        for character in run:
            if chosen is not None and (character.isspace() or ord(character) in chosen.characters):
                target = chosen.family
            else:
                target = _symbol_font(character)
                if target is None:
                    missing += character
                    target = piece_family
            if target != piece_family and piece:
                result.append(FontRun(piece, piece_family, script, direction, missing))
                piece, missing = "", ""
            piece_family = target
            piece += character
        if piece:
            result.append(FontRun(piece, piece_family, script, direction, missing))
    return _merged(result)


def _merged(runs: list[FontRun]) -> list[FontRun]:
    merged: list[FontRun] = []
    for run in runs:
        if merged and (merged[-1].family, merged[-1].script, merged[-1].direction) == (run.family, run.script, run.direction):
            last = merged[-1]
            merged[-1] = FontRun(last.text + run.text, last.family, last.script, last.direction, last.missing + run.missing)
        else:
            merged.append(run)
    return merged


def scripts_in(text: str) -> set[str]:
    return {script for character in text if (script := script_of(character)) is not None}
