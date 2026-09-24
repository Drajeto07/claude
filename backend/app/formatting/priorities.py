from enum import IntEnum


class Priority(IntEnum):
    """Resolution tiers (spec §7.9 / корекции.docx §16), lower wins. Every tier is
    named even where nothing produces it yet (IMPORTED_REQUIREMENT, AI_INFERENCE),
    so a future producer slots in without renumbering anything."""

    LIVE_OVERRIDE = 1
    INSTRUCTION = 2
    IMPORTED_REQUIREMENT = 3
    CUSTOM_TEMPLATE = 4
    BUILTIN_TEMPLATE = 5
    AI_INFERENCE = 6
    DEFAULT = 7
