from enum import IntEnum


class Priority(IntEnum):
    """Resolution tiers (spec §7.9 / корекции.docx §16), lower wins. Every tier is
    named even where nothing produces it yet (IMPORTED_REQUIREMENT, AI_INFERENCE).

    SOURCE_DOCUMENT is the uploaded file's own formatting (its Word styles and
    direct formatting): it makes an import look like the original, and sits
    below the templates so that applying one still restyles the document.
    Adding it moved AI_INFERENCE (never stored anywhere) and DEFAULT down one;
    rules stored with the old DEFAULT value (7) are identified by source
    "default" and replaced the next time formatting is applied."""

    LIVE_OVERRIDE = 1
    INSTRUCTION = 2
    IMPORTED_REQUIREMENT = 3
    CUSTOM_TEMPLATE = 4
    BUILTIN_TEMPLATE = 5
    SOURCE_DOCUMENT = 6
    AI_INFERENCE = 7
    DEFAULT = 8
