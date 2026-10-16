"""The fonts the exports can use, and what each can draw (tracker FONT-001): for every font file
of a family the PDF export knows (export/fonts.py) or a script needs, read once with
fontTools -- the characters its cmap covers, by script; its metrics; whether its licence lets
it be embedded (OS/2 fsType). The FontResolver (font_resolver.py) chooses from it.

A script counts as covered when the font draws every character of that script's sample
(letters a text in it can't do without); a font that may not be embedded (fsType 2:
restricted licence) is listed, never used in a PDF."""

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont, TTLibError

from app.export.fonts import _FAMILY_FILES, SCRIPT_FAMILY_FILES, _font_files

logger = logging.getLogger(__name__)

# Each script's sample: characters a text in it needs (ISO 15924 codes, as translation/language.py).
SAMPLES: dict[str, str] = {
    "Latn": "AaBbZzÀàÉéÇçŠšŽžŁłÆæØøÅåÑñÜüß",
    "Cyrl": "АаБбВвЖжЩщЪъЬьЮюЯяЁёІіЇїЄєЂђЋћЏџ",
    "Grek": "ΑαΒβΓγΔδΩωάέήίόύώ",
    "Arab": "ابتثجحخدذرزسشصضطظعغفقكلمنهوي",
    "Hebr": "אבגדהוזחטיכלמנסעפצקרשת",
    "Deva": "अआइईउऊएऐओऔकखगघचछजझटठडढणतथदधनपफबभमयरलवशषसह्ािीुूेैोौंः",
    "Thai": "กขคงจฉชซญณดตถทนบปผพฟภมยรลวศษสหอฮะาำิีึืุู่้๊๋",
    "Hani": "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意建月公无系军很情者最立代想已通并提直题党程展五果料象员革位入常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放决西被干做必战先回则任取据处府队南给色光门即保治北造百规热领七海口东导器压志世金增争济阶油思术极交受联什认六共权收证改清己美再采转更单风切打白教速花带安场身车例真务具万每目至达走积示议声报斗完类八离华名确才科张信马节话米整空元况今集温传土许步群广石记需段研界拉林律叫且究观越织装影算低持音众书布复容儿须际商非验连断深难近矿千周委素技备半办青省列习响约支般史感劳便团往酸历市克何除消构府称太准精值号率族维划选标写存候毛亲快效斯院查江型眼王按格养易置派层片始却专状育厂京识适属圆包火住调满县局照参红细引听该铁价严",
    "Hang": "가나다라마바사아자차카타파하한국어글",
    "Kana": "あいうえおかきくけこアイウエオカキクケコ",
}
# Families a script's text falls back to, best first (installed ones only are used).
SCRIPT_FAMILIES: dict[str, tuple[str, ...]] = {
    "Arab": ("Arial", "Times New Roman", "Segoe UI", "Tahoma", "Noto Naskh Arabic", "Noto Sans Arabic", "DejaVu Sans"),
    "Hebr": ("Arial", "Times New Roman", "Segoe UI", "David", "Noto Sans Hebrew", "DejaVu Sans"),
    "Deva": ("Nirmala UI", "Mangal", "Noto Sans Devanagari", "Lohit Devanagari"),
    "Thai": ("Leelawadee UI", "Tahoma", "Noto Sans Thai", "Loma"),
    "Hani": ("Microsoft YaHei", "SimSun", "Noto Sans CJK SC", "Noto Sans SC", "WenQuanYi Zen Hei"),
    "Kana": ("Yu Gothic", "MS Gothic", "Noto Sans CJK JP", "Noto Sans JP"),
    "Hang": ("Malgun Gothic", "Noto Sans CJK KR", "Noto Sans KR", "NanumGothic"),
    "Grek": ("Arial", "Times New Roman", "DejaVu Sans", "Liberation Sans"),
    "Cyrl": ("Arial", "Times New Roman", "DejaVu Sans", "Liberation Sans"),
}
# fsType bit 1 (value 2): restricted licence -- may not be embedded.
_RESTRICTED = 0x0002


@dataclass(frozen=True, slots=True)
class CatalogueFont:
    family: str
    path: Path
    subfont: int  # within a .ttc
    scripts: frozenset[str]  # covered (every character of the script's sample)
    units_per_em: int
    ascent: int
    descent: int
    embeddable: bool
    characters: frozenset[int] = field(repr=False, default=frozenset())

    def draws(self, text: str) -> bool:
        return all(ord(character) in self.characters or character.isspace() for character in text)


def all_family_files() -> dict[str, tuple[str, str | None, str | None, str | None]]:
    return {**_FAMILY_FILES, **SCRIPT_FAMILY_FILES}


def _read(family: str, path: Path) -> CatalogueFont | None:
    try:
        if path.suffix.lower() == ".ttc":
            font = TTCollection(str(path), lazy=True).fonts[0]
        else:
            font = TTFont(str(path), lazy=True)
        cmap = font.getBestCmap() or {}
        head, hhea = font["head"], font["hhea"]
        fs_type = font["OS/2"].fsType if "OS/2" in font else 0
    except (TTLibError, OSError, KeyError, AttributeError) as exc:
        logger.warning("Font %s at %s couldn't be read: %s", family, path, type(exc).__name__)
        return None
    characters = frozenset(cmap)
    scripts = frozenset(script for script, sample in SAMPLES.items() if all(ord(character) in characters for character in sample))
    return CatalogueFont(
        family=family, path=path, subfont=0, scripts=scripts, units_per_em=head.unitsPerEm, ascent=hhea.ascent,
        descent=hhea.descent, embeddable=not fs_type & _RESTRICTED, characters=characters,
    )


@lru_cache
def catalogue() -> dict[str, CatalogueFont]:
    """Family -> its regular face, for every known family installed here."""
    found = _font_files()
    fonts = {}
    for family, files in all_family_files().items():
        path = found.get(files[0].lower())
        if path is not None and (font := _read(family, path)) is not None:
            fonts[family] = font
    return fonts


def covering(script: str) -> list[CatalogueFont]:
    """The installed, embeddable fonts that cover `script`, its preferred families first."""
    fonts = catalogue()
    preferred = [fonts[family] for family in SCRIPT_FAMILIES.get(script, ()) if family in fonts]
    others = sorted((font for font in fonts.values() if font not in preferred), key=lambda font: font.family)
    return [font for font in [*preferred, *others] if script in font.scripts and font.embeddable]
