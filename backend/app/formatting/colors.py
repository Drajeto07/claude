import re

# The colour names both exporters can render; anything else must be hex.
# Shared by docx_export.py, pdf_export.py and style_system.py's validation.
NAMED_COLORS: dict[str, str] = {
    "red": "FF0000",
    "blue": "0000FF",
    "green": "008000",
    "black": "000000",
    "white": "FFFFFF",
    "gray": "808080",
    "grey": "808080",
    "yellow": "FFFF00",
    "orange": "FFA500",
    "purple": "800080",
}

_HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


def is_renderable_color(value: str) -> bool:
    """True for values every renderer understands: #rgb, #rrggbb or a NAMED_COLORS key."""
    value = value.strip()
    return bool(_HEX_COLOR.fullmatch(value)) or value.lower() in NAMED_COLORS
