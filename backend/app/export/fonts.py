"""TrueType fonts for PDF export. reportlab's built-in fonts (Helvetica, Times,
Courier) only cover Western European letters: Cyrillic comes out as black
boxes. So the PDF uses real fonts found on the machine, embedded in the file:
the document's own font when it's installed, otherwise a close match of the
same kind (sans-serif, serif, monospace) that covers Cyrillic.

Searched: PDF_FONT_DIRS (setting), then the usual system font folders. A
Linux server needs e.g. the fonts-liberation or fonts-dejavu package; with
no TrueType font at all, export falls back to the built-in fonts and logs a
warning."""

import logging
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont, TTFError

from app.config import get_settings

logger = logging.getLogger(__name__)

# family -> (regular, bold, italic, bold italic) file names, as the font vendors ship them.
_FAMILY_FILES: dict[str, tuple[str, str | None, str | None, str | None]] = {
    "Arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "Times New Roman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "Courier New": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
    "Calibri": ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "Cambria": ("cambria.ttc", "cambriab.ttf", "cambriai.ttf", "cambriaz.ttf"),
    "Georgia": ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"),
    "Verdana": ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "Tahoma": ("tahoma.ttf", "tahomabd.ttf", None, None),
    "Segoe UI": ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "Consolas": ("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"),
    "Garamond": ("gara.ttf", "garabd.ttf", "garait.ttf", None),
    "Book Antiqua": ("bkant.ttf", "antquab.ttf", "antquai.ttf", "antquabi.ttf"),
    "Liberation Sans": ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf", "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf"),
    "Liberation Serif": ("LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf", "LiberationSerif-Italic.ttf", "LiberationSerif-BoldItalic.ttf"),
    "Liberation Mono": ("LiberationMono-Regular.ttf", "LiberationMono-Bold.ttf", "LiberationMono-Italic.ttf", "LiberationMono-BoldItalic.ttf"),
    # Metric-compatible stand-ins (METRIC_COMPATIBLE), as Linux packages ship them (fonts-crosextra-*, fonts-croscore).
    "Carlito": ("Carlito-Regular.ttf", "Carlito-Bold.ttf", "Carlito-Italic.ttf", "Carlito-BoldItalic.ttf"),
    "Caladea": ("Caladea-Regular.ttf", "Caladea-Bold.ttf", "Caladea-Italic.ttf", "Caladea-BoldItalic.ttf"),
    "Arimo": ("Arimo-Regular.ttf", "Arimo-Bold.ttf", "Arimo-Italic.ttf", "Arimo-BoldItalic.ttf"),
    "Tinos": ("Tinos-Regular.ttf", "Tinos-Bold.ttf", "Tinos-Italic.ttf", "Tinos-BoldItalic.ttf"),
    "Cousine": ("Cousine-Regular.ttf", "Cousine-Bold.ttf", "Cousine-Italic.ttf", "Cousine-BoldItalic.ttf"),
    "DejaVu Sans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"),
    "Segoe UI Symbol": ("seguisym.ttf", None, None, None),
    "DejaVu Serif": ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf", "DejaVuSerif-Italic.ttf", "DejaVuSerif-BoldItalic.ttf"),
    "DejaVu Sans Mono": ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf", "DejaVuSansMono-Oblique.ttf", "DejaVuSansMono-BoldOblique.ttf"),
}

# Families other scripts fall back to (export/font_catalogue.py, FONT-002), by their files.
SCRIPT_FAMILY_FILES: dict[str, tuple[str, str | None, str | None, str | None]] = {
    "Nirmala UI": ("nirmala.ttf", "nirmalab.ttf", None, None),
    "Mangal": ("mangal.ttf", "mangalb.ttf", None, None),
    "Noto Sans Devanagari": ("NotoSansDevanagari-Regular.ttf", "NotoSansDevanagari-Bold.ttf", None, None),
    "Lohit Devanagari": ("Lohit-Devanagari.ttf", None, None, None),
    "Leelawadee UI": ("leelawui.ttf", "leelauib.ttf", None, None),
    "Noto Sans Thai": ("NotoSansThai-Regular.ttf", "NotoSansThai-Bold.ttf", None, None),
    "Loma": ("Loma.ttf", "Loma-Bold.ttf", None, None),
    "Microsoft YaHei": ("msyh.ttc", "msyhbd.ttc", None, None),
    "SimSun": ("simsun.ttc", None, None, None),
    "Noto Sans CJK SC": ("NotoSansCJK-Regular.ttc", "NotoSansCJK-Bold.ttc", None, None),
    "Noto Sans SC": ("NotoSansSC-Regular.ttf", "NotoSansSC-Bold.ttf", None, None),
    "WenQuanYi Zen Hei": ("wqy-zenhei.ttc", None, None, None),
    "Yu Gothic": ("yugothm.ttc", "yugothb.ttc", None, None),
    "MS Gothic": ("msgothic.ttc", None, None, None),
    "Noto Sans CJK JP": ("NotoSansCJK-Regular.ttc", "NotoSansCJK-Bold.ttc", None, None),
    "Noto Sans JP": ("NotoSansJP-Regular.ttf", "NotoSansJP-Bold.ttf", None, None),
    "Malgun Gothic": ("malgun.ttf", "malgunbd.ttf", None, None),
    "Noto Sans CJK KR": ("NotoSansCJK-Regular.ttc", "NotoSansCJK-Bold.ttc", None, None),
    "Noto Sans KR": ("NotoSansKR-Regular.ttf", "NotoSansKR-Bold.ttf", None, None),
    "NanumGothic": ("NanumGothic.ttf", "NanumGothicBold.ttf", None, None),
    "Noto Naskh Arabic": ("NotoNaskhArabic-Regular.ttf", "NotoNaskhArabic-Bold.ttf", None, None),
    "Noto Sans Arabic": ("NotoSansArabic-Regular.ttf", "NotoSansArabic-Bold.ttf", None, None),
    "Noto Sans Hebrew": ("NotoSansHebrew-Regular.ttf", "NotoSansHebrew-Bold.ttf", None, None),
    "David": ("david.ttf", "davidbd.ttf", None, None),
}
# Fonts made with the same widths as a common one (metric-compatible): a document set in the
# first breaks its lines the same in any of these, so they stand in for it first (FONT-005).
METRIC_COMPATIBLE: dict[str, tuple[str, ...]] = {
    "Arial": ("Liberation Sans", "Arimo"),
    "Helvetica": ("Arial", "Liberation Sans", "Arimo"),
    "Times New Roman": ("Liberation Serif", "Tinos"),
    "Times": ("Times New Roman", "Liberation Serif", "Tinos"),
    "Courier New": ("Liberation Mono", "Cousine"),
    "Calibri": ("Carlito",),
    "Cambria": ("Caladea",),
}
# What to use instead of a font that isn't installed, by kind, best first.
_FALLBACKS = {
    "sans": ("Arial", "Liberation Sans", "DejaVu Sans", "Calibri", "Segoe UI", "Verdana", "Tahoma"),
    "serif": ("Times New Roman", "Liberation Serif", "DejaVu Serif", "Georgia", "Cambria", "Book Antiqua"),
    "mono": ("Courier New", "Liberation Mono", "DejaVu Sans Mono", "Consolas"),
}
_SERIF_HINTS = ("times", "georgia", "cambria", "garamond", "antiqua", "palatino", "serif", "roman", "book", "minion", "baskerville", "didot", "constantia")
_MONO_HINTS = ("mono", "courier", "consolas", "code", "menlo", "monaco", "typewriter", "console")
# reportlab's own fonts, the last resort (no Cyrillic).
_BUILTIN = {
    "sans": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
    "serif": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "mono": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"),
}


@dataclass(frozen=True)
class PdfFont:
    """Registered font names for one family; <b>/<i> in paragraph markup pick
    the variants automatically."""

    regular: str
    bold: str
    italic: str
    bold_italic: str
    embedded: bool

    def variant(self, bold: bool, italic: bool) -> str:
        if bold and italic:
            return self.bold_italic
        if bold:
            return self.bold
        return self.italic if italic else self.regular


def _font_dirs() -> list[Path]:
    configured = [Path(part) for part in get_settings().pdf_font_dirs.split(os.pathsep) if part.strip()]
    if sys.platform.startswith("win"):
        windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"
        system = [windows, local]
    elif sys.platform == "darwin":
        system = [Path("/Library/Fonts"), Path("/System/Library/Fonts"), Path.home() / "Library" / "Fonts"]
    else:
        system = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts"]
    return [*configured, *system]


@lru_cache
def _font_files() -> dict[str, Path]:
    """File name (lower case) -> path, over every font folder, searched once."""
    found: dict[str, Path] = {}
    for directory in _font_dirs():
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.suffix.lower() in (".ttf", ".ttc") and path.name.lower() not in found:
                found[path.name.lower()] = path
    return found


def font_kind(family: str) -> str:
    """"sans", "serif" or "mono": the kind of font a family name is, by its name."""
    name = family.lower()
    if any(hint in name for hint in _MONO_HINTS):
        return "mono"
    if any(hint in name for hint in _SERIF_HINTS) and "sans" not in name:
        return "serif"
    return "sans"


@lru_cache
def _register(family: str) -> PdfFont | None:
    files = _FAMILY_FILES.get(family) or SCRIPT_FAMILY_FILES.get(family)
    available = _font_files()
    if files is None or files[0].lower() not in available:
        return None
    names: list[str] = []
    for index, file_name in enumerate(files):
        path = available.get(file_name.lower()) if file_name else None
        if path is None:
            names.append(names[0])  # a missing bold/italic falls back to the regular face
            continue
        name = f"{family}-{index}"
        try:
            pdfmetrics.registerFont(TTFont(name, str(path), subfontIndex=0))
        except (TTFError, OSError) as exc:
            if index == 0:
                logger.warning("Could not load font %s from %s: %s", family, path, exc)
                return None
            names.append(names[0])
            continue
        names.append(name)
    regular, bold, italic, bold_italic = names
    for is_bold, is_italic, name in ((0, 0, regular), (1, 0, bold), (0, 1, italic), (1, 1, bold_italic)):
        addMapping(regular, is_bold, is_italic, name)
    return PdfFont(regular, bold, italic, bold_italic, embedded=True)


@lru_cache
def resolved_family(family: str | None) -> str | None:
    """The installed family that draws `family`: itself, else the best of the same kind;
    None when no TrueType font is installed at all."""
    requested = (family or "").strip().strip("\"'")
    known = {**_FAMILY_FILES, **SCRIPT_FAMILY_FILES}
    exact = next((name for name in known if name.lower() == requested.lower()), None)
    if exact and _register(exact):
        return exact
    stand_ins = fallback_stack(requested)[1 if requested else 0 :]  # after the family itself, when one was named
    return next((candidate for candidate in stand_ins if candidate in known and _register(candidate)), None)


def fallback_stack(family: str | None) -> list[str]:
    """What stands in for `family`, best first, after the family itself: the fonts made with its
    widths, then the best of its kind (FONT-005). A PDF export draws the first installed; the
    editor's CSS lists them all (frontend/editor/fontFallbacks.json, written from this)."""
    requested = (family or "").strip().strip("\"'")
    compatible = next((names for name, names in METRIC_COMPATIBLE.items() if name.lower() == requested.lower()), ())
    stack = [requested] if requested else []
    for candidate in (*compatible, *_FALLBACKS[font_kind(requested) if requested else "sans"]):
        if candidate.lower() not in {name.lower() for name in stack}:
            stack.append(candidate)
    return stack


@lru_cache
def pdf_font(family: str | None) -> PdfFont:
    """The font to draw `family` with: itself when installed, else the best
    installed font of the same kind, else a built-in one."""
    chosen = resolved_family(family)
    if chosen is not None and (font := _register(chosen)):
        return font
    requested = (family or "").strip().strip("\"'")
    kind = font_kind(requested) if requested else "sans"
    logger.warning("No TrueType font found for PDF export; Cyrillic and other non-Latin text will not render.")
    return PdfFont(*_BUILTIN[kind], embedded=False)


# Fonts with many symbols, for a character a document's own font doesn't have (a bullet).
_SYMBOL_FAMILIES = ("Segoe UI Symbol", "DejaVu Sans", "Segoe UI", "Arial", "Liberation Sans")


def _draws(name: str, character: str) -> bool:
    try:
        font = pdfmetrics.getFont(name)
    except KeyError:
        return False
    face = getattr(font, "face", None)
    glyphs = getattr(face, "charToGlyph", None)
    if glyphs is not None:
        return ord(character) in glyphs
    try:  # a built-in font draws what WinAnsi has
        character.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return True


def font_for(character: str, preferred: str) -> str:
    """A registered font that draws `character`: `preferred` when it can, else the
    first installed font with many symbols that can, else `preferred` anyway."""
    if _draws(preferred, character):
        return preferred
    for family in _SYMBOL_FAMILIES:
        font = _register(family)
        if font is not None and _draws(font.regular, character):
            return font.regular
    return preferred


def shaping_available() -> bool:
    """Whether text can be shaped here (HarfBuzz, through uharfbuzz): Arabic letters joined,
    Devanagari conjuncts formed. Without it such text is drawn letter by letter, and said so."""
    try:
        import uharfbuzz  # noqa: F401
    except ImportError:
        return False
    return True
